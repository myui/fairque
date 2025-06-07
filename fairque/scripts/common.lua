-- common.lua: Shared functions and utilities for FairQueue Lua scripts
-- This file contains common functions used across multiple FairQueue operations

-- Constants
local CRITICAL_SUFFIX = ":critical"
local NORMAL_SUFFIX = ":normal"
local STATS_KEY = "queue:stats"

-- Error codes
local ERR_INVALID_ARGS = "ERR_INVALID_ARGS"
local ERR_TASK_NOT_FOUND = "ERR_TASK_NOT_FOUND"
local ERR_INVALID_PRIORITY = "ERR_INVALID_PRIORITY"
local ERR_QUEUE_OPERATION = "ERR_QUEUE_OPERATION"

-- Helper functions

-- Get queue key for user and priority
-- @param user_id: User identifier
-- @param priority: Priority value (1-6)
-- @return: Queue key string
local function get_queue_key(user_id, priority)
    if priority == 6 then
        return "queue:user:" .. user_id .. CRITICAL_SUFFIX
    else
        return "queue:user:" .. user_id .. NORMAL_SUFFIX
    end
end

-- Validate priority value
-- @param priority: Priority value to validate
-- @return: true if valid, false otherwise
local function is_valid_priority(priority)
    local p = tonumber(priority)
    return p and p >= 1 and p <= 6
end

-- Calculate priority score for normal queue ordering
-- Higher score = higher priority for processing
-- Formula: created_at + (priority_weight * elapsed_time)
-- @param created_at: Task creation timestamp
-- @param priority: Priority value (1-5, not 6)
-- @param current_time: Current timestamp
-- @return: Calculated score
local function calculate_score(created_at, priority, current_time)
    local priority_weight = tonumber(priority) / 5.0
    local elapsed_time = current_time - tonumber(created_at)
    return tonumber(created_at) + (priority_weight * elapsed_time)
end

-- Validate task arguments
-- @param task_args: Array of task arguments [task_id, user_id, priority, payload, retry_count, max_retries, created_at, execute_after]
-- @return: true if valid, error message if invalid
local function validate_task_args(task_args)
    if #task_args ~= 8 then
        return false, "Task must have exactly 8 arguments"
    end
    
    local task_id, user_id, priority, payload, retry_count, max_retries, created_at, execute_after = 
        task_args[1], task_args[2], task_args[3], task_args[4], task_args[5], task_args[6], task_args[7], task_args[8]
    
    -- Validate required fields
    if not task_id or task_id == "" then
        return false, "task_id cannot be empty"
    end
    
    if not user_id or user_id == "" then
        return false, "user_id cannot be empty"
    end
    
    if not is_valid_priority(priority) then
        return false, "Invalid priority: " .. tostring(priority)
    end
    
    if not payload then
        return false, "payload cannot be nil"
    end
    
    -- Validate numeric fields
    if not tonumber(retry_count) or tonumber(retry_count) < 0 then
        return false, "retry_count must be non-negative number"
    end
    
    if not tonumber(max_retries) or tonumber(max_retries) < 0 then
        return false, "max_retries must be non-negative number"
    end
    
    if not tonumber(created_at) or tonumber(created_at) <= 0 then
        return false, "created_at must be positive number"
    end
    
    if not tonumber(execute_after) or tonumber(execute_after) <= 0 then
        return false, "execute_after must be positive number"
    end
    
    return true, nil
end

-- Create task hash data for Redis storage
-- @param task_args: Array of task arguments
-- @return: Hash table for Redis HMSET
local function create_task_hash(task_args)
    return {
        "task_id", task_args[1],
        "user_id", task_args[2],
        "priority", task_args[3],
        "payload", task_args[4],
        "retry_count", task_args[5],
        "max_retries", task_args[6],
        "created_at", task_args[7],
        "execute_after", task_args[8]
    }
end

-- Update statistics atomically
-- @param stat_key: Statistics key name
-- @param increment: Value to increment (default 1)
-- @param current_time: Current timestamp for time-based stats
local function update_stats(stat_key, increment, current_time)
    increment = increment or 1
    current_time = current_time or redis.call("TIME")[1]
    
    -- Update counter
    redis.call("HINCRBY", STATS_KEY, stat_key, increment)
    
    -- Update timestamp for rate calculations
    redis.call("HSET", STATS_KEY, stat_key .. ":last_update", current_time)
end

-- Get current Redis server time as float
-- @return: Current time as float seconds
local function get_current_time()
    local time_result = redis.call("TIME")
    return tonumber(time_result[1]) + (tonumber(time_result[2]) / 1000000)
end

-- Check if task is ready to execute
-- @param execute_after: Task execute_after timestamp
-- @param current_time: Current timestamp
-- @return: true if ready, false otherwise
local function is_task_ready(execute_after, current_time)
    return tonumber(execute_after) <= current_time
end

-- Build error response
-- @param error_code: Error code constant
-- @param message: Error message
-- @param details: Optional error details table
-- @return: Error response table
local function build_error_response(error_code, message, details)
    local response = {
        success = false,
        error_code = error_code,
        message = message
    }
    
    if details then
        response.details = details
    end
    
    return response
end

-- Build success response
-- @param data: Response data
-- @param stats: Optional statistics to include
-- @return: Success response table
local function build_success_response(data, stats)
    local response = {
        success = true,
        data = data
    }
    
    if stats then
        response.stats = stats
    end
    
    return response
end

-- Serialize response to JSON-like string for Redis return
-- @param response: Response table
-- @return: Serialized string
local function serialize_response(response)
    -- Simple JSON-like serialization for basic types
    local function serialize_value(val)
        if type(val) == "string" then
            return '"' .. val .. '"'
        elseif type(val) == "number" or type(val) == "boolean" then
            return tostring(val)
        elseif type(val) == "table" then
            local items = {}
            local is_array = true
            local max_index = 0
            
            -- Check if table is array-like
            for k, v in pairs(val) do
                if type(k) ~= "number" then
                    is_array = false
                    break
                end
                max_index = math.max(max_index, k)
            end
            
            if is_array and max_index == #val then
                -- Array format
                for i = 1, #val do
                    table.insert(items, serialize_value(val[i]))
                end
                return "[" .. table.concat(items, ",") .. "]"
            else
                -- Object format
                for k, v in pairs(val) do
                    table.insert(items, '"' .. tostring(k) .. '":' .. serialize_value(v))
                end
                return "{" .. table.concat(items, ",") .. "}"
            end
        else
            return "null"
        end
    end
    
    return serialize_value(response)
end

-- Export functions for use in other scripts
return {
    -- Constants
    CRITICAL_SUFFIX = CRITICAL_SUFFIX,
    NORMAL_SUFFIX = NORMAL_SUFFIX,
    STATS_KEY = STATS_KEY,
    
    -- Error codes
    ERR_INVALID_ARGS = ERR_INVALID_ARGS,
    ERR_TASK_NOT_FOUND = ERR_TASK_NOT_FOUND,
    ERR_INVALID_PRIORITY = ERR_INVALID_PRIORITY,
    ERR_QUEUE_OPERATION = ERR_QUEUE_OPERATION,
    
    -- Functions
    get_queue_key = get_queue_key,
    is_valid_priority = is_valid_priority,
    calculate_score = calculate_score,
    validate_task_args = validate_task_args,
    create_task_hash = create_task_hash,
    update_stats = update_stats,
    get_current_time = get_current_time,
    is_task_ready = is_task_ready,
    build_error_response = build_error_response,
    build_success_response = build_success_response,
    serialize_response = serialize_response
}
