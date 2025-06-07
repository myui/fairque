-- stats.lua: Statistics operations for FairQueue monitoring
-- This script provides comprehensive statistics retrieval and queue size monitoring

-- Constants
local CRITICAL_SUFFIX = ":critical"
local NORMAL_SUFFIX = ":normal"
local STATS_KEY = "queue:stats"

-- Error codes
local ERR_INVALID_ARGS = "ERR_INVALID_ARGS"
local ERR_INVALID_OPERATION = "ERR_INVALID_OPERATION"

-- Helper functions
local function get_queue_key(user_id, priority)
    if tonumber(priority) == 6 then
        return "queue:user:" .. user_id .. CRITICAL_SUFFIX
    else
        return "queue:user:" .. user_id .. NORMAL_SUFFIX
    end
end

local function get_current_time()
    local time_result = redis.call("TIME")
    return tonumber(time_result[1]) + (tonumber(time_result[2]) / 1000000)
end

-- Get queue sizes for a specific user
-- @param user_id: User identifier
-- @return: Table with critical_size and normal_size
local function get_user_queue_sizes(user_id)
    local critical_queue = get_queue_key(user_id, 6)
    local normal_queue = get_queue_key(user_id, 1)

    local critical_size = redis.call("LLEN", critical_queue)
    local normal_size = redis.call("ZCARD", normal_queue)

    return {
        critical_size = critical_size,
        normal_size = normal_size,
        total_size = critical_size + normal_size
    }
end

-- Get comprehensive statistics
-- @return: Table with all statistics
local function get_comprehensive_stats()
    local current_time = get_current_time()

    -- Get all stats from hash
    local all_stats = redis.call("HGETALL", STATS_KEY)
    local stats = {}

    -- Convert array to key-value pairs
    for i = 1, #all_stats, 2 do
        local key = all_stats[i]
        local value = tonumber(all_stats[i + 1]) or all_stats[i + 1]
        stats[key] = value
    end

    -- Add current timestamp
    stats.current_time = current_time

    -- Calculate rates (tasks per second) for key metrics
    local rate_metrics = {
        "tasks_pushed_total",
        "tasks_popped_total", 
        "tasks_pushed_critical",
        "tasks_pushed_normal",
        "tasks_popped_critical",
        "tasks_popped_normal"
    }

    for _, metric in ipairs(rate_metrics) do
        local last_update_key = metric .. ":last_update"
        local last_update = stats[last_update_key]
        local count = stats[metric]

        if last_update and count and count > 0 then
            local time_diff = current_time - tonumber(last_update)
            if time_diff > 0 then
                stats[metric .. "_rate"] = count / time_diff
            else
                stats[metric .. "_rate"] = 0
            end
        else
            stats[metric .. "_rate"] = 0
        end
    end

    return stats
end

-- Get queue sizes for multiple users
-- @param user_list: Array of user IDs
-- @return: Table with per-user queue sizes
local function get_batch_queue_sizes(user_list)
    local results = {}
    local total_critical = 0
    local total_normal = 0

    for _, user_id in ipairs(user_list) do
        local sizes = get_user_queue_sizes(user_id)
        results[user_id] = sizes
        total_critical = total_critical + sizes.critical_size
        total_normal = total_normal + sizes.normal_size
    end

    results.totals = {
        critical_size = total_critical,
        normal_size = total_normal,
        total_size = total_critical + total_normal
    }

    return results
end

-- Reset specific statistics (for testing/maintenance)
-- @param stat_keys: Array of statistic keys to reset
-- @return: Number of keys reset
local function reset_stats(stat_keys)
    if not stat_keys or #stat_keys == 0 then
        return 0
    end

    local reset_count = 0
    for _, key in ipairs(stat_keys) do
        local exists = redis.call("HEXISTS", STATS_KEY, key)
        if exists == 1 then
            redis.call("HDEL", STATS_KEY, key)
            reset_count = reset_count + 1
        end
    end

    return reset_count
end

-- Get basic metrics for CLI display
-- @return: Table with essential metrics
local function get_basic_metrics()
    local stats = get_comprehensive_stats()
    return {
        total_tasks = (stats.tasks_pushed_total or 0) - (stats.tasks_popped_total or 0),
        active_workers = 0, -- Will be calculated from worker heartbeats
        push_rate = stats.tasks_pushed_total_rate or 0,
        pop_rate = stats.tasks_popped_total_rate or 0
    }
end

-- Get detailed metrics including queue breakdown
-- @return: Table with detailed metrics
local function get_detailed_metrics()
    local basic = get_basic_metrics()
    local stats = get_comprehensive_stats()

    -- Add detailed breakdown
    basic.critical_tasks = (stats.tasks_pushed_critical or 0) - (stats.tasks_popped_critical or 0)
    basic.normal_tasks = (stats.tasks_pushed_normal or 0) - (stats.tasks_popped_normal or 0)
    basic.critical_push_rate = stats.tasks_pushed_critical_rate or 0
    basic.normal_push_rate = stats.tasks_pushed_normal_rate or 0
    basic.failed_tasks = stats.tasks_failed_total or 0

    return basic
end

-- Get worker-specific metrics
-- @param worker_id: Worker identifier or "all"
-- @return: Table with worker metrics
local function get_worker_metrics(worker_id)
    -- For now, return placeholder structure
    -- Will be enhanced when worker heartbeat system is implemented
    if worker_id == "all" then
        return {
            workers = {},
            total_workers = 0,
            active_workers = 0
        }
    else
        return {
            worker_id = worker_id,
            status = "unknown",
            active_tasks = 0,
            assigned_users = {},
            last_heartbeat = nil
        }
    end
end

-- Get queue-specific metrics for user(s)
-- @param user_id: User identifier or "all"
-- @return: Table with queue metrics
local function get_queue_metrics(user_id)
    if user_id == "all" then
        -- Get all users from configuration (placeholder for now)
        local all_queues = {}
        local total_critical = 0
        local total_normal = 0

        -- Scan for queue keys to find users
        local queue_keys = redis.call("KEYS", "queue:user:*")
        local users_found = {}

        for _, key in ipairs(queue_keys) do
            local user = string.match(key, "queue:user:([^:]+)")
            if user and not users_found[user] then
                users_found[user] = true
                local sizes = get_user_queue_sizes(user)
                all_queues[user] = sizes
                total_critical = total_critical + sizes.critical_size
                total_normal = total_normal + sizes.normal_size
            end
        end

        return {
            queues = all_queues,
            totals = {
                critical_size = total_critical,
                normal_size = total_normal,
                total_size = total_critical + total_normal
            }
        }
    else
        return get_user_queue_sizes(user_id)
    end
end

-- Main statistics operation dispatcher
-- ARGV[1]: operation ("get_stats", "get_queue_sizes", "get_batch_sizes", "reset_stats", "get_metrics", "get_health")
-- ARGV[2]: optional parameter (user_id for get_queue_sizes, user_list for get_batch_sizes, stat_keys for reset_stats, level for get_metrics)
-- ARGV[3]: optional target parameter for get_metrics (user_id, worker_id, or "all")
-- Returns: JSON-like response with requested data

-- Validate arguments
if #ARGV < 1 then
    return '{"success":false,"error_code":"ERR_INVALID_ARGS","message":"Expected at least 1 argument (operation), got ' .. #ARGV .. '"}'
end

local operation = ARGV[1]
local param = ARGV[2]
local target = ARGV[3]

-- Operation dispatcher
local response_data = nil
local current_time = get_current_time()

if operation == "get_stats" then
    -- Get comprehensive statistics
    response_data = get_comprehensive_stats()

elseif operation == "get_queue_sizes" then
    -- Get queue sizes for specific user
    if not param or param == "" then
        return '{"success":false,"error_code":"ERR_INVALID_ARGS","message":"user_id parameter required for get_queue_sizes operation"}'
    end

    response_data = get_user_queue_sizes(param)
    response_data.user_id = param
    response_data.checked_at = current_time

elseif operation == "get_batch_sizes" then
    -- Get queue sizes for multiple users
    if not param or param == "" then
        return '{"success":false,"error_code":"ERR_INVALID_ARGS","message":"user_list parameter required for get_batch_sizes operation"}'
    end

    -- Parse comma-separated user list
    local users = {}
    for user_id in string.gmatch(param, "([^,]+)") do
        table.insert(users, user_id)
    end

    if #users == 0 then
        return '{"success":false,"error_code":"ERR_INVALID_ARGS","message":"No valid users found in user_list"}'
    end

    response_data = get_batch_queue_sizes(users)
    response_data.checked_at = current_time

elseif operation == "reset_stats" then
    -- Reset specific statistics
    if not param or param == "" then
        return '{"success":false,"error_code":"ERR_INVALID_ARGS","message":"stat_keys parameter required for reset_stats operation"}'
    end

    -- Parse comma-separated stat keys
    local stat_keys = {}
    for key in string.gmatch(param, "([^,]+)") do
        table.insert(stat_keys, key)
    end

    if #stat_keys == 0 then
        return '{"success":false,"error_code":"ERR_INVALID_ARGS","message":"No valid stat_keys found"}'
    end

    local reset_count = reset_stats(stat_keys)
    response_data = {
        reset_count = reset_count,
        reset_keys = stat_keys,
        reset_at = current_time
    }

elseif operation == "get_health" then
    -- Get health check information
    local stats = get_comprehensive_stats()

    response_data = {
        status = "healthy",
        active_tasks = stats.tasks_active or 0,
        total_pushed = stats.tasks_pushed_total or 0,
        total_popped = stats.tasks_popped_total or 0,
        uptime_seconds = current_time,
        checked_at = current_time
    }

    -- Determine health status based on metrics
    local active_threshold = 10000  -- Alert if more than 10k active tasks

    if (stats.tasks_active or 0) > active_threshold then
        response_data.status = "warning"
        response_data.warnings = response_data.warnings or {}
        table.insert(response_data.warnings, "Active tasks exceed threshold: " .. (stats.tasks_active or 0))
    end

elseif operation == "get_metrics" then
    -- Get metrics based on level and target
    local level = param or "basic"
    local target_param = target or "all"

    if level == "basic" then
        response_data = get_basic_metrics()
    elseif level == "detailed" then
        response_data = get_detailed_metrics()
    elseif level == "worker" then
        response_data = get_worker_metrics(target_param)
    elseif level == "queue" then
        response_data = get_queue_metrics(target_param)
    else
        return '{"success":false,"error_code":"ERR_INVALID_ARGS","message":"Invalid level parameter for get_metrics: ' .. level .. '"}'
    end

else
    return '{"success":false,"error_code":"ERR_INVALID_OPERATION","message":"Unknown operation: ' .. operation .. '"}'
end

-- Build success response
local response = {
    success = true,
    operation = operation,
    data = response_data,
    timestamp = current_time
}

-- Simple JSON serialization
local function serialize_table(tbl)
    local items = {}
    for k, v in pairs(tbl) do
        local value_str
        if type(v) == "string" then
            value_str = '"' .. v .. '"'
        elseif type(v) == "table" then
            value_str = serialize_table(v)
        elseif v == nil then
            value_str = "null"
        else
            value_str = tostring(v)
        end
        table.insert(items, '"' .. k .. '":' .. value_str)
    end
    return "{" .. table.concat(items, ",") .. "}"
end

return serialize_table(response)
