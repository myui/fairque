-- pop.lua with unified state management and fq: prefix
-- This script implements fair scheduling with automatic QUEUED -> STARTED transition

-- Redis key prefixes with fq: namespace
local QUEUE_PREFIX = "fq:queue:user:"
local STATE_PREFIX = "fq:state:"
local TASK_PREFIX = "fq:task:"
local STATS_KEY = "fq:stats"

-- Error codes
local ERR_INVALID_ARGS = "ERR_INVALID_ARGS"
local ERR_NO_TASKS = "ERR_NO_TASKS"
local ERR_QUEUE_OPERATION = "ERR_QUEUE_OPERATION"

-- Helper functions
local function get_current_time()
    local time_result = redis.call("TIME")
    return tonumber(time_result[1]) + (tonumber(time_result[2]) / 1000000)
end

local function get_queue_key(user_id, priority)
    if tonumber(priority) == 6 then
        return QUEUE_PREFIX .. user_id .. ":critical"
    else
        return QUEUE_PREFIX .. user_id .. ":normal"
    end
end

local function update_stats(stat_key, increment)
    increment = increment or 1
    local current_time = get_current_time()
    
    redis.call("HINCRBY", STATS_KEY, stat_key, increment)
    redis.call("HSET", STATS_KEY, stat_key .. ":last_update", current_time)
end

local function is_task_ready(execute_after, current_time)
    return tonumber(execute_after) <= current_time
end

local function validate_queued_task(task_id)
    local state = redis.call("HGET", TASK_PREFIX .. task_id, "state")
    return state == "queued"
end

-- Try to pop task from critical queue (FIFO)
local function try_pop_critical(user_id, current_time)
    local critical_queue = get_queue_key(user_id, 6)
    
    local tasks = redis.call("LRANGE", critical_queue, 0, -1)
    
    if #tasks == 0 then
        return nil
    end
    
    for i, task_id in ipairs(tasks) do
        if validate_queued_task(task_id) then
            local task_hash = TASK_PREFIX .. task_id
            local execute_after = redis.call("HGET", task_hash, "execute_after")
            
            if execute_after and is_task_ready(execute_after, current_time) then
                local removed = redis.call("LREM", critical_queue, 1, task_id)
                if removed > 0 then
                    return task_id
                end
            end
        end
    end
    
    return nil
end

-- Try to pop task from normal queue (priority sorted)
local function try_pop_normal(user_id, current_time)
    local normal_queue = get_queue_key(user_id, 1)
    
    local tasks_with_scores = redis.call("ZREVRANGE", normal_queue, 0, 9, "WITHSCORES")
    
    if #tasks_with_scores == 0 then
        return nil
    end
    
    for i = 1, #tasks_with_scores, 2 do
        local task_id = tasks_with_scores[i]
        
        if validate_queued_task(task_id) then
            local task_hash = TASK_PREFIX .. task_id
            local execute_after = redis.call("HGET", task_hash, "execute_after")
            
            if execute_after and is_task_ready(execute_after, current_time) then
                local removed = redis.call("ZREM", normal_queue, task_id)
                if removed > 0 then
                    return task_id
                end
            end
        else
            -- Clean up stale queue entry
            redis.call("ZREM", normal_queue, task_id)
        end
    end
    
    return nil
end

-- Try to pop task from user queues
local function try_pop_from_user(user_id, current_time)
    local task_id = try_pop_critical(user_id, current_time)
    if task_id then
        return task_id
    end
    
    return try_pop_normal(user_id, current_time)
end

-- Main pop operation
-- ARGV: [user_list, worker_id]

-- Validate arguments
if #ARGV ~= 2 then
    return '{"success":false,"error_code":"' .. ERR_INVALID_ARGS .. '","message":"Expected 2 arguments (user_list, worker_id), got ' .. #ARGV .. '"}'
end

local user_list_str = ARGV[1]
local worker_id = ARGV[2]

if not user_list_str or user_list_str == "" then
    return '{"success":false,"error_code":"' .. ERR_INVALID_ARGS .. '","message":"user_list cannot be empty"}'
end

if not worker_id or worker_id == "" then
    return '{"success":false,"error_code":"' .. ERR_INVALID_ARGS .. '","message":"worker_id cannot be empty"}'
end

-- Parse comma-separated user list
local users = {}
for user_id in string.gmatch(user_list_str, "([^,]+)") do
    table.insert(users, user_id)
end

if #users == 0 then
    return '{"success":false,"error_code":"' .. ERR_INVALID_ARGS .. '","message":"No valid users found in user_list"}'
end

local current_time = get_current_time()

-- Try to find a ready task from users (fair scheduling)
local task_id = nil
local selected_user = nil

for _, user_id in ipairs(users) do
    task_id = try_pop_from_user(user_id, current_time)
    if task_id then
        selected_user = user_id
        break
    end
end

-- If no task found, return empty result
if not task_id then
    return '{"success":true,"task":null,"message":"No ready tasks available"}'
end

-- Retrieve full task data
local task_hash = TASK_PREFIX .. task_id
local task_data = redis.call("HMGET", task_hash, 
    "task_id", "user_id", "priority", "payload", "retry_count", "max_retries", "created_at", "execute_after")

-- Validate task data exists
if not task_data[1] then
    return '{"success":false,"error_code":"' .. ERR_QUEUE_OPERATION .. '","message":"Task data not found after pop"}'
end

-- Transition QUEUED -> STARTED
redis.call("ZREM", STATE_PREFIX .. "queued", task_id)
redis.call("ZADD", STATE_PREFIX .. "started", current_time, task_id)
redis.call("HMSET", task_hash,
    "state", "started",
    "started_at", current_time,
    "worker_id", worker_id)

-- Update statistics
update_stats("tasks_popped_total", 1)
update_stats("tasks_started", 1)

local user_stat_key = "user:" .. selected_user .. ":tasks_popped"
update_stats(user_stat_key, 1)

local priority = tonumber(task_data[3])
local priority_stat_key = "priority:" .. tostring(priority) .. ":tasks_popped"
update_stats(priority_stat_key, 1)

if priority == 6 then
    update_stats("tasks_popped_critical", 1)
else
    update_stats("tasks_popped_normal", 1)
end

-- Build response data
local response_data = {
    task_id = task_data[1],
    user_id = task_data[2],
    priority = tonumber(task_data[3]),
    payload = task_data[4],
    retry_count = tonumber(task_data[5]),
    max_retries = tonumber(task_data[6]),
    created_at = tonumber(task_data[7]),
    execute_after = tonumber(task_data[8]),
    popped_at = current_time,
    selected_user = selected_user,
    worker_id = worker_id
}

-- Build success response
local response = {
    success = true,
    task = response_data,
    stats = {
        tasks_started = redis.call("HGET", STATS_KEY, "tasks_started"),
        tasks_popped_total = redis.call("HGET", STATS_KEY, "tasks_popped_total")
    }
}

-- Simple JSON serialization with proper escaping
local function escape_json_string(str)
    if str == nil then
        return "null"
    end
    -- Escape double quotes and backslashes
    str = string.gsub(str, "\\", "\\\\")
    str = string.gsub(str, '"', '\\"')
    str = string.gsub(str, "\n", "\\n")
    str = string.gsub(str, "\r", "\\r")
    str = string.gsub(str, "\t", "\\t")
    return '"' .. str .. '"'
end

local function serialize_table(tbl)
    local items = {}
    for k, v in pairs(tbl) do
        local value_str
        if type(v) == "string" then
            value_str = escape_json_string(v)
        elseif type(v) == "table" then
            value_str = serialize_table(v)
        elseif v == nil then
            value_str = "null"
        else
            value_str = tostring(v)
        end
        table.insert(items, escape_json_string(k) .. ":" .. value_str)
    end
    return "{" .. table.concat(items, ",") .. "}"
end

return serialize_table(response)