 -- =========================================================
-- Phase 5 — PostgreSQL Schema
-- E-Commerce Product Analytics & Conversion Funnel Analysis
-- =========================================================

-- Drop tables if re-running (safe for dev/iteration)
DROP TABLE IF EXISTS events CASCADE;
DROP TABLE IF EXISTS sessions CASCADE;
DROP TABLE IF EXISTS items CASCADE;
DROP TABLE IF EXISTS categories CASCADE;
DROP TABLE IF EXISTS visitors CASCADE;

-- ---------------------------------------------------------
-- Dimension: visitors
-- ---------------------------------------------------------
CREATE TABLE visitors (
    visitorid TEXT PRIMARY KEY
);

-- ---------------------------------------------------------
-- Dimension: categories (self-referencing hierarchy)
-- ---------------------------------------------------------
CREATE TABLE categories (
    categoryid TEXT PRIMARY KEY,
    parentid TEXT
);

-- ---------------------------------------------------------
-- Dimension: items
-- ---------------------------------------------------------
CREATE TABLE items (
    itemid TEXT PRIMARY KEY,
    categoryid TEXT,
    available TEXT
);

-- ---------------------------------------------------------
-- Dimension: sessions
-- ---------------------------------------------------------
CREATE TABLE sessions (
    session_id TEXT PRIMARY KEY,
    visitorid TEXT NOT NULL
);

-- ---------------------------------------------------------
-- Fact table: events
-- ---------------------------------------------------------
CREATE TABLE events (
    event_id SERIAL PRIMARY KEY,
    visitorid TEXT NOT NULL,
    session_id TEXT NOT NULL,
    itemid TEXT NOT NULL,
    event_type TEXT NOT NULL,          -- 'view', 'addtocart', 'transaction'
    funnel_stage TEXT NOT NULL,        -- 'Product View', 'Add to Cart', 'Purchase'
    transactionid TEXT,
    categoryid TEXT,
    parentid TEXT,
    available TEXT,
    event_timestamp TIMESTAMP NOT NULL
);

-- =========================================================
-- Indexes (added AFTER bulk load for faster import)
-- =========================================================
CREATE INDEX idx_events_visitor ON events(visitorid);
CREATE INDEX idx_events_session ON events(session_id);
CREATE INDEX idx_events_item ON events(itemid);
CREATE INDEX idx_events_type ON events(event_type);
CREATE INDEX idx_events_timestamp ON events(event_timestamp);
CREATE INDEX idx_items_category ON items(categoryid);


--2nd query 
DROP TABLE IF EXISTS staging_events;

CREATE TABLE staging_events (
    timestamp TIMESTAMP,
    visitorid TEXT,
    event TEXT,
    itemid TEXT,
    transactionid TEXT,
    session_id TEXT,
    funnel_stage TEXT,
    categoryid TEXT,
    available TEXT,
    parentid TEXT
);

--3rd query
-- 1. Clear everything first
TRUNCATE TABLE events, sessions, items, categories, visitors RESTART IDENTITY CASCADE;

-- 2. Visitors (fine as DISTINCT — one column, no conflict possible)
INSERT INTO visitors (visitorid)
SELECT DISTINCT visitorid FROM staging_events;

-- 3. Categories (GROUP BY, not DISTINCT — this is what fixes your error)
INSERT INTO categories (categoryid, parentid)
SELECT categoryid, MAX(parentid) AS parentid
FROM staging_events
WHERE categoryid IS NOT NULL
GROUP BY categoryid;

-- 4. Items (GROUP BY, not DISTINCT)
INSERT INTO items (itemid, categoryid, available)
SELECT itemid, MAX(categoryid) AS categoryid, MAX(available) AS available
FROM staging_events
WHERE itemid IS NOT NULL
GROUP BY itemid;

-- 5. Sessions (GROUP BY, not DISTINCT)
INSERT INTO sessions (session_id, visitorid)
SELECT session_id, MAX(visitorid) AS visitorid
FROM staging_events
WHERE session_id IS NOT NULL
GROUP BY session_id;

-- 6. Events (fine as plain SELECT — every row is a distinct event, duplicates are expected/valid here)
INSERT INTO events (visitorid, session_id, itemid, event_type, funnel_stage, transactionid, categoryid, parentid, available, event_timestamp)
SELECT visitorid, session_id, itemid, event, funnel_stage, transactionid, categoryid, parentid, available, timestamp
FROM staging_events;

--verification
SELECT funnel_stage, COUNT(*) 
FROM events 
GROUP BY funnel_stage
ORDER BY COUNT(*) DESC;


--30 EDA questions
-- 1. Total unique visitors
SELECT COUNT(DISTINCT visitorid) AS total_visitors FROM events;

-- 2. Total unique sessions
SELECT COUNT(DISTINCT session_id) AS total_sessions FROM events;

-- 3. Total unique items interacted with
SELECT COUNT(DISTINCT itemid) AS total_items FROM events;

-- 4. Total events by type
SELECT funnel_stage, COUNT(*) FROM events GROUP BY funnel_stage ORDER BY COUNT(*) DESC;

-- 5. Average events per session
SELECT ROUND(COUNT(*)::numeric / COUNT(DISTINCT session_id), 2) AS avg_events_per_session FROM events;

-- 6. Average events per visitor
SELECT ROUND(COUNT(*)::numeric / COUNT(DISTINCT visitorid), 2) AS avg_events_per_visitor FROM events;

-- 7. Sessions per visitor distribution
SELECT session_count, COUNT(*) AS num_visitors FROM (
    SELECT visitorid, COUNT(DISTINCT session_id) AS session_count
    FROM events GROUP BY visitorid
) t GROUP BY session_count ORDER BY session_count LIMIT 20;

-- 8. Average session duration (in minutes)
SELECT ROUND(AVG(duration_min), 2) AS avg_session_duration_min FROM (
    SELECT session_id, 
           EXTRACT(EPOCH FROM (MAX(event_timestamp) - MIN(event_timestamp)))/60 AS duration_min
    FROM events GROUP BY session_id
) t;

-- 9. Single-event ("bounce") sessions — sessions with only 1 event
SELECT COUNT(*) AS bounce_sessions FROM (
    SELECT session_id FROM events GROUP BY session_id HAVING COUNT(*) = 1
) t;

-- 10. Bounce rate (% of sessions with only 1 event)
SELECT ROUND(100.0 * (
    SELECT COUNT(*) FROM (SELECT session_id FROM events GROUP BY session_id HAVING COUNT(*)=1) b
) / COUNT(DISTINCT session_id), 2) AS bounce_rate_pct
FROM events;

-- 11. Events by hour of day (peak hours)
SELECT EXTRACT(HOUR FROM event_timestamp) AS hour_of_day, COUNT(*) AS event_count
FROM events GROUP BY hour_of_day ORDER BY hour_of_day;

-- 12. Events by day of week
SELECT TO_CHAR(event_timestamp, 'Day') AS day_of_week, COUNT(*) AS event_count
FROM events GROUP BY day_of_week ORDER BY event_count DESC;

-- 13. Daily event trend over time
SELECT DATE(event_timestamp) AS event_date, COUNT(*) AS event_count
FROM events GROUP BY event_date ORDER BY event_date;

-- 14. Daily purchase trend
SELECT DATE(event_timestamp) AS event_date, COUNT(*) AS purchases
FROM events WHERE funnel_stage = 'Purchase'
GROUP BY event_date ORDER BY event_date;

-- 15. Peak purchase hour
SELECT EXTRACT(HOUR FROM event_timestamp) AS hour_of_day, COUNT(*) AS purchases
FROM events WHERE funnel_stage = 'Purchase'
GROUP BY hour_of_day ORDER BY purchases DESC LIMIT 5;

-- 16. Top 10 most-viewed products
SELECT itemid, COUNT(*) AS views FROM events
WHERE funnel_stage = 'Product View' GROUP BY itemid ORDER BY views DESC LIMIT 10;

-- 17. Top 10 most-purchased products
SELECT itemid, COUNT(*) AS purchases FROM events
WHERE funnel_stage = 'Purchase' GROUP BY itemid ORDER BY purchases DESC LIMIT 10;

-- 18. Top 10 most-added-to-cart products
SELECT itemid, COUNT(*) AS adds FROM events
WHERE funnel_stage = 'Add to Cart' GROUP BY itemid ORDER BY adds DESC LIMIT 10;

-- 19. Products viewed but NEVER purchased (dead weight in catalog)
SELECT COUNT(DISTINCT itemid) AS never_purchased_items FROM events
WHERE funnel_stage = 'Product View' 
AND itemid NOT IN (SELECT itemid FROM events WHERE funnel_stage = 'Purchase');

-- 20. Item-level conversion rate (view -> purchase), top 10 converting items with min 50 views
SELECT itemid,
    COUNT(*) FILTER (WHERE funnel_stage = 'Product View') AS views,
    COUNT(*) FILTER (WHERE funnel_stage = 'Purchase') AS purchases,
    ROUND(100.0 * COUNT(*) FILTER (WHERE funnel_stage = 'Purchase') / 
          NULLIF(COUNT(*) FILTER (WHERE funnel_stage = 'Product View'), 0), 2) AS conversion_pct
FROM events GROUP BY itemid
HAVING COUNT(*) FILTER (WHERE funnel_stage = 'Product View') >= 50
ORDER BY conversion_pct DESC LIMIT 10;

-- 21. Top 10 categories by views
SELECT categoryid, COUNT(*) AS views FROM events
WHERE funnel_stage = 'Product View' AND categoryid != 'unknown'
GROUP BY categoryid ORDER BY views DESC LIMIT 10;

-- 22. Top 10 categories by purchases
SELECT categoryid, COUNT(*) AS purchases FROM events
WHERE funnel_stage = 'Purchase' AND categoryid != 'unknown'
GROUP BY categoryid ORDER BY purchases DESC LIMIT 10;

-- 23. Category-level conversion rate (min 100 views)
SELECT categoryid,
    COUNT(*) FILTER (WHERE funnel_stage = 'Product View') AS views,
    COUNT(*) FILTER (WHERE funnel_stage = 'Purchase') AS purchases,
    ROUND(100.0 * COUNT(*) FILTER (WHERE funnel_stage = 'Purchase') / 
          NULLIF(COUNT(*) FILTER (WHERE funnel_stage = 'Product View'), 0), 2) AS conversion_pct
FROM events WHERE categoryid != 'unknown'
GROUP BY categoryid
HAVING COUNT(*) FILTER (WHERE funnel_stage = 'Product View') >= 100
ORDER BY conversion_pct DESC LIMIT 10;

-- 24. Worst-performing categories (high views, zero/low purchases)
SELECT categoryid,
    COUNT(*) FILTER (WHERE funnel_stage = 'Product View') AS views,
    COUNT(*) FILTER (WHERE funnel_stage = 'Purchase') AS purchases
FROM events WHERE categoryid != 'unknown'
GROUP BY categoryid
HAVING COUNT(*) FILTER (WHERE funnel_stage = 'Product View') >= 100
ORDER BY purchases ASC, views DESC LIMIT 10;

-- 25. Returning vs one-time visitors (based on session count)
SELECT CASE WHEN session_count = 1 THEN 'One-time' ELSE 'Returning' END AS visitor_type,
       COUNT(*) AS num_visitors
FROM (SELECT visitorid, COUNT(DISTINCT session_id) AS session_count FROM events GROUP BY visitorid) t
GROUP BY visitor_type;

-- 26. Visitors who purchased more than once
SELECT COUNT(*) AS repeat_purchasers FROM (
    SELECT visitorid FROM events WHERE funnel_stage = 'Purchase'
    GROUP BY visitorid HAVING COUNT(DISTINCT transactionid) > 1
) t;

-- 27. % of visitors who ever added to cart
SELECT ROUND(100.0 * COUNT(DISTINCT visitorid) FILTER (WHERE funnel_stage = 'Add to Cart') 
    / COUNT(DISTINCT visitorid), 2) AS pct_visitors_added_to_cart
FROM events;

-- 28. % of visitors who ever purchased
SELECT ROUND(100.0 * COUNT(DISTINCT visitorid) FILTER (WHERE funnel_stage = 'Purchase') 
    / COUNT(DISTINCT visitorid), 2) AS pct_visitors_purchased
FROM events;

-- 29. Average items per completed order (transaction)
SELECT ROUND(AVG(item_count), 2) AS avg_items_per_order FROM (
    SELECT transactionid, COUNT(*) AS item_count
    FROM events WHERE funnel_stage = 'Purchase' AND transactionid IS NOT NULL
    GROUP BY transactionid
) t;

-- 30. Cart abandonment rate (added to cart but never purchased that item)
SELECT ROUND(100.0 * (
    COUNT(*) FILTER (WHERE funnel_stage = 'Add to Cart') - COUNT(*) FILTER (WHERE funnel_stage = 'Purchase')
) / NULLIF(COUNT(*) FILTER (WHERE funnel_stage = 'Add to Cart'), 0), 2) AS cart_abandonment_pct
FROM events;


--fix of category and availablity
-- Fix the events table: swap the mislabeled columns
CREATE TABLE events_fixed AS
SELECT 
    event_id, visitorid, session_id, itemid, event_type, funnel_stage, transactionid,
    available AS categoryid_fixed,
    categoryid AS available_fixed,
    parentid, event_timestamp
FROM events;

ALTER TABLE events_fixed RENAME COLUMN categoryid_fixed TO categoryid;
ALTER TABLE events_fixed RENAME COLUMN available_fixed TO available;

DROP TABLE events;
ALTER TABLE events_fixed RENAME TO events;

-- Fix the items table the same way
CREATE TABLE items_fixed AS
SELECT itemid, available AS categoryid_fixed, categoryid AS available_fixed
FROM items;

ALTER TABLE items_fixed RENAME COLUMN categoryid_fixed TO categoryid;
ALTER TABLE items_fixed RENAME COLUMN available_fixed TO available;

DROP TABLE items;
ALTER TABLE items_fixed RENAME TO items;


--verify
SELECT categoryid, COUNT(DISTINCT itemid) FROM items GROUP BY categoryid ORDER BY 2 DESC LIMIT 10;


--redoing of old question due to mismatch
-- 21. Top 10 categories by views
SELECT categoryid, COUNT(*) AS views FROM events
WHERE funnel_stage = 'Product View' AND categoryid != 'unknown'
GROUP BY categoryid ORDER BY views DESC LIMIT 10;

-- 22. Top 10 categories by purchases
SELECT categoryid, COUNT(*) AS purchases FROM events
WHERE funnel_stage = 'Purchase' AND categoryid != 'unknown'
GROUP BY categoryid ORDER BY purchases DESC LIMIT 10;

-- 23. Category-level conversion rate (min 100 views)
SELECT categoryid,
    COUNT(*) FILTER (WHERE funnel_stage = 'Product View') AS views,
    COUNT(*) FILTER (WHERE funnel_stage = 'Purchase') AS purchases,
    ROUND(100.0 * COUNT(*) FILTER (WHERE funnel_stage = 'Purchase') / 
          NULLIF(COUNT(*) FILTER (WHERE funnel_stage = 'Product View'), 0), 2) AS conversion_pct
FROM events WHERE categoryid != 'unknown'
GROUP BY categoryid
HAVING COUNT(*) FILTER (WHERE funnel_stage = 'Product View') >= 100
ORDER BY conversion_pct DESC LIMIT 10;

-- 24. Worst-performing categories (high views, low purchases)
SELECT categoryid,
    COUNT(*) FILTER (WHERE funnel_stage = 'Product View') AS views,
    COUNT(*) FILTER (WHERE funnel_stage = 'Purchase') AS purchases
FROM events WHERE categoryid != 'unknown'
GROUP BY categoryid
HAVING COUNT(*) FILTER (WHERE funnel_stage = 'Product View') >= 100
ORDER BY purchases ASC, views DESC LIMIT 10;

--phase8
-- Master segmentation query: one row per visitor with all segment flags
CREATE TABLE visitor_segments AS
SELECT 
    v.visitorid,
    COUNT(DISTINCT e.session_id) AS session_count,
    COUNT(*) FILTER (WHERE e.funnel_stage = 'Product View') AS view_count,
    COUNT(*) FILTER (WHERE e.funnel_stage = 'Add to Cart') AS cart_count,
    COUNT(*) FILTER (WHERE e.funnel_stage = 'Purchase') AS purchase_count,
    COUNT(DISTINCT e.transactionid) FILTER (WHERE e.funnel_stage = 'Purchase') AS distinct_orders,
    
    CASE WHEN COUNT(DISTINCT e.session_id) = 1 THEN 'One-time' ELSE 'Returning' END AS visitor_type,
    
    CASE WHEN COUNT(*) FILTER (WHERE e.funnel_stage = 'Purchase') > 0 THEN 'High-Value' 
         ELSE 'Non-Purchaser' END AS value_segment,
    
    CASE WHEN COUNT(DISTINCT e.transactionid) FILTER (WHERE e.funnel_stage = 'Purchase') > 1 THEN 'Repeat Buyer'
         WHEN COUNT(DISTINCT e.transactionid) FILTER (WHERE e.funnel_stage = 'Purchase') = 1 THEN 'One-time Buyer'
         WHEN COUNT(*) FILTER (WHERE e.funnel_stage = 'Add to Cart') > 0 THEN 'Cart Abandoner'
         ELSE 'Browser Only' END AS behavior_segment

FROM visitors v
JOIN events e ON v.visitorid = e.visitorid
GROUP BY v.visitorid;

--segment summary size
SELECT behavior_segment, COUNT(*) AS num_visitors,
       ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2) AS pct_of_total
FROM visitor_segments
GROUP BY behavior_segment
ORDER BY num_visitors DESC;

SELECT behavior_segment,
       ROUND(AVG(session_count), 2) AS avg_sessions,
       ROUND(AVG(view_count), 2) AS avg_views,
       ROUND(AVG(cart_count), 2) AS avg_cart_adds
FROM visitor_segments
GROUP BY behavior_segment
ORDER BY avg_sessions DESC;

--phase9
-- Step 1: Find each visitor's first-ever activity week (their cohort)
CREATE TABLE visitor_cohorts AS
SELECT visitorid, 
       DATE_TRUNC('week', MIN(event_timestamp)) AS cohort_week
FROM events
GROUP BY visitorid;

-- Step 2: For every event, calculate which "week number" since cohort start it falls in
CREATE TABLE cohort_activity AS
SELECT 
    vc.cohort_week,
    e.visitorid,
    DATE_TRUNC('week', e.event_timestamp) AS activity_week,
    EXTRACT(DAY FROM (DATE_TRUNC('week', e.event_timestamp) - vc.cohort_week)) / 7 AS week_number
FROM events e
JOIN visitor_cohorts vc ON e.visitorid = vc.visitorid;

-- Step 3: Retention matrix — visitors active per cohort per week_number
SELECT 
    cohort_week,
    week_number,
    COUNT(DISTINCT visitorid) AS active_visitors
FROM cohort_activity
GROUP BY cohort_week, week_number
ORDER BY cohort_week, week_number;
--new query
WITH cohort_sizes AS (
    SELECT cohort_week, COUNT(DISTINCT visitorid) AS cohort_size
    FROM visitor_cohorts GROUP BY cohort_week
),
retention AS (
    SELECT cohort_week, week_number, COUNT(DISTINCT visitorid) AS active_visitors
    FROM cohort_activity
    GROUP BY cohort_week, week_number
)
SELECT r.cohort_week, r.week_number, r.active_visitors, cs.cohort_size,
       ROUND(100.0 * r.active_visitors / cs.cohort_size, 2) AS retention_pct
FROM retention r
JOIN cohort_sizes cs ON r.cohort_week = cs.cohort_week
WHERE r.week_number BETWEEN 0 AND 8   -- first 8 weeks
ORDER BY r.cohort_week, r.week_number;

--new query
SELECT vc.cohort_week,
       COUNT(DISTINCT vc.visitorid) AS cohort_size,
       COUNT(DISTINCT e.visitorid) FILTER (WHERE e.funnel_stage = 'Purchase') AS purchasers,
       ROUND(100.0 * COUNT(DISTINCT e.visitorid) FILTER (WHERE e.funnel_stage = 'Purchase') 
             / COUNT(DISTINCT vc.visitorid), 2) AS purchase_rate_pct
FROM visitor_cohorts vc
JOIN events e ON vc.visitorid = e.visitorid
GROUP BY vc.cohort_week
ORDER BY vc.cohort_week;

SELECT COUNT(*) FROM visitor_segments;
SELECT COUNT(*) FROM cohort_activity;
ALTER USER postgres WITH PASSWORD 'newpassword123';
