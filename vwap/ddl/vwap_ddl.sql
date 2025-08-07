file -inlinebatch END_OF_BATCH

-- Dummy table (often used for initial setup or health checks)
CREATE TABLE dummy
(x varchar(1) primary key);

-- Table to store VWAP state for stock ticks
CREATE TABLE stocktick_vmap
(symbol varchar(10) not null
,tickdate timestamp not null
,timescale varchar(10) not null
,open_price decimal not null
,high_price decimal not null
,low_price decimal not null
,close_price decimal not null
,volume decimal not null
,total_value decimal not null
,vmap decimal
,primary key (symbol,tickdate,timescale));

-- Partition the stocktick_vmap table by symbol for distributed processing
partition TABLE stocktick_vmap on column symbol;

-- Session VWAP state table
CREATE TABLE vwap_state (
    symbol VARCHAR(10) NOT NULL,
    session_start TIMESTAMP NOT NULL,
    cumulative_value_volume DECIMAL,
    cumulative_volume DECIMAL,
    last_update TIMESTAMP,
    PRIMARY KEY (symbol,session_start)
);
-- Partition the vwap_state table by symbol
partition TABLE vwap_state on column symbol;

-- Stream to capture all incoming ticks, partitioned by symbol, and export to a target (ALERTS)
CREATE STREAM ALL_TICKS PARTITION ON COLUMN SYMBOL EXPORT TO TARGET ALERTS (
   Symbol varchar(10) NOT NULL,
   Tickdate timestamp NOT NULL,
   Value decimal NOT NULL,
   Volume decimal NOT NULL
);

-- View to summarize ticks by symbol
CREATE VIEW TICKS_SUMMARY (
Symbol,
Ticks_count) as select Symbol, count(*) from ALL_TICKS group by symbol;

-- Stored procedure for reporting tick session anchor
CREATE PROCEDURE
   PARTITION ON TABLE stocktick_vmap COLUMN symbol
   FROM CLASS com.voltactivedata.voltdb.storedProcedures.ReportTickSessionAnchor;

-- Stored procedure to reset the database by deleting data from stocktick_vmap
CREATE PROCEDURE ResetDatabase AS
DELETE FROM stocktick_vmap;
END_OF_BATCH
