-- ✅ Create the database if it doesn't exist
CREATE DATABASE IF NOT EXISTS health_surveillance
CHARACTER SET utf8mb4
COLLATE utf8mb4_general_ci;

-- ✅ Switch to the database
USE health_surveillance;

-- ✅ Create table for Health/Disease Reports
CREATE TABLE IF NOT EXISTS reports (
  id INT AUTO_INCREMENT PRIMARY KEY,         -- Unique ID for each report
  name VARCHAR(100),                         -- Name of the person (optional)
  age INT NOT NULL,                          -- Age of the person (required)
  location VARCHAR(100) NOT NULL,            -- Location (required)
  symptoms TEXT NOT NULL,                    -- Symptoms (required)
  contact VARCHAR(20),                       -- Contact number (optional)
  report_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP  -- Time of submission
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
