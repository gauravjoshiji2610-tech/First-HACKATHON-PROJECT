// Smart Health Surveillance - Integrated Backend
require('dotenv').config();
const express = require('express');
const mysql = require('mysql2/promise');
const bodyParser = require('body-parser');
const cors = require('cors');
const path = require('path');
const axios = require('axios');

const app = express();
const PORT = process.env.PORT || 3000;

// Middleware
app.use(cors());
app.use(bodyParser.json());
app.use(express.static(path.join(__dirname, 'public')));

// MySQL connection pool
const pool = mysql.createPool({
  host: process.env.MYSQL_HOST || 'localhost',
  user: process.env.MYSQL_USER || 'root',
  password: process.env.MYSQL_PASSWORD || '',
  database: process.env.MYSQL_DB || 'health_surveillance',
  waitForConnections: true,
  connectionLimit: 10,
  queueLimit: 0,
});

// Utils
function simpleRiskFromInputs({ symptoms = '', turbidity, pH, bacteria_count }) {
  const s = (symptoms || '').toLowerCase();
  const t = parseFloat(turbidity || 0);
  const b = parseFloat(bacteria_count || 0);
  let risk = 'Low', disease = 'Unknown';
  if (b > 150 || t > 30 || (s.includes('fever') && s.includes('diarrhea'))) {
    risk = 'High'; disease = 'Typhoid';
  } else if (b > 60 || t > 15 || s.includes('diarrhea')) {
    risk = 'Medium'; disease = 'Diarrhea';
  } else if (b > 20 || s.includes('jaundice')) {
    risk = 'Low'; disease = 'Hepatitis A';
  }
  return { risk, disease };
}

async function sendSmsIfConfigured(text) {
  const sid = process.env.TWILIO_SID, auth = process.env.TWILIO_AUTH;
  const from = process.env.TWILIO_FROM, to = process.env.ALERT_PHONE;
  if (!sid || !auth || !from || !to) return; // optional
  try {
    const twilio = require('twilio')(sid, auth);
    await twilio.messages.create({ body: text, from, to });
    console.log('📨 SMS sent');
  } catch (e) {
    console.warn('SMS failed:', e.message);
  }
}

// ------------------- Routes (Pages) -------------------
app.get('/', (req, res) => res.sendFile(path.join(__dirname, 'public', 'dashboard.html')));

// ------------------- APIs -----------------------------

// Submit Health Report (AI-first flow)
app.post('/api/health-report', async (req, res) => {
  try {
    const { name, age, location, symptoms, contact, turbidity, pH, bacteria_count } = req.body || {};
    if (!age || !location || !symptoms) return res.status(400).json({ message: 'age, location, symptoms required' });

    // Quick heuristic risk
    const { risk, disease } = simpleRiskFromInputs({ symptoms, turbidity, pH, bacteria_count });

    // Link to recent water test (optional)
    let water_test_id = null;
    if (location) {
      const [wt] = await pool.query(
        "SELECT id FROM water_tests WHERE location=? ORDER BY test_time DESC LIMIT 1", [location]
      );
      water_test_id = wt.length ? wt[0].id : null;
    }

    await pool.query(
      `INSERT INTO health_reports (name, age, location, symptoms, contact, disease_predicted, risk, turbidity, pH, bacteria_count, water_test_id)
       VALUES (?,?,?,?,?,?,?,?,?,?,?)`,
      [name || null, age, location, symptoms, contact || null, disease, risk, turbidity || null, pH || null, bacteria_count || null, water_test_id]
    );

    // Fetch recent reports for AI
    const [reports] = await pool.query("SELECT * FROM health_reports ORDER BY report_time DESC LIMIT 500");
    // Attach latest water snapshot per location
    const [waters] = await pool.query("SELECT * FROM water_tests ORDER BY test_time DESC");
    const latestWaterByLoc = {};
    for (const w of waters) if (!latestWaterByLoc[w.location]) latestWaterByLoc[w.location] = w;
    const aiPayload = reports.map(r => ({
      id: r.id,
      location: r.location,
      symptoms: r.symptoms,
      turbidity: r.turbidity ?? (latestWaterByLoc[r.location]?.turbidity ?? 0),
      pH: r.pH ?? (latestWaterByLoc[r.location]?.pH ?? 7),
      bacteria_count: r.bacteria_count ?? (latestWaterByLoc[r.location]?.bacteria_count ?? 0),
      report_time: r.report_time,
    }));

    let aiResult = { overall_risk: 'Low', high_risk_locations: [], totals: {} };
    try {
      const aiRes = await axios.post(process.env.AI_URL || 'http://127.0.0.1:5000/analyze', aiPayload, { timeout: 5000 });
      aiResult = aiRes.data;
    } catch (e) {
      console.warn('AI call failed:', e.message);
    }

    // Alert logic
    if (aiResult?.overall_risk === 'High') {
      await pool.query(
        "INSERT INTO alerts (alert_type, location, severity, message) VALUES (?,?,?,?)",
        ['OutbreakWarning', 'Multiple', 'High', 'High outbreak risk detected by AI']
      );
      await sendSmsIfConfigured('ALERT: High outbreak risk detected by AI (Multiple locations)');
    }
    if (Array.isArray(aiResult?.high_risk_locations)) {
      for (const loc of aiResult.high_risk_locations) {
        await pool.query(
          "INSERT INTO alerts (alert_type, location, severity, message) VALUES (?,?,?,?)",
          ['LocalOutbreakRisk', loc, 'High', `AI flagged ${loc} as high risk`]
        );
      }
    }

    res.json({ message: '✅ Report saved and analyzed', heuristic: { disease, risk }, ai: aiResult });
  } catch (err) {
    console.error(err);
    res.status(500).json({ message: '❌ Internal Server Error' });
  }
});

// Submit Water Test
app.post('/api/water-test', async (req, res) => {
  try {
    const { location, turbidity, pH, bacteria_count } = req.body || {};
    if (!location || turbidity === undefined || pH === undefined || bacteria_count === undefined) {
      return res.status(400).json({ message: 'location, turbidity, pH, bacteria_count required' });
    }
    const [r] = await pool.query(
      "INSERT INTO water_tests (location, turbidity, pH, bacteria_count) VALUES (?,?,?,?)",
      [location, turbidity, pH, bacteria_count]
    );

    // Optional quick contamination alert
    if (parseFloat(bacteria_count) > 150 || parseFloat(turbidity) > 30) {
      await pool.query(
        "INSERT INTO alerts (alert_type, location, severity, message) VALUES (?,?,?,?)",
        ['WaterContamination', location, 'High', 'Latest water test shows high contamination']
      );
      await sendSmsIfConfigured(`ALERT: High water contamination at ${location}`);
    }

    res.json({ message: '✅ Water test saved', id: r.insertId });
  } catch (err) {
    console.error(err);
    res.status(500).json({ message: '❌ Internal Server Error' });
  }
});

// Get Active Alerts
app.get('/api/alerts', async (req, res) => {
  const [rows] = await pool.query("SELECT * FROM alerts WHERE status='Active' ORDER BY alert_time DESC LIMIT 100");
  res.json(rows);
});

// On-demand AI (for analysis page)
app.get('/api/analyze', async (req, res) => {
  try {
    const [reports] = await pool.query("SELECT * FROM health_reports ORDER BY report_time DESC LIMIT 500");
    const [waters] = await pool.query("SELECT * FROM water_tests ORDER BY test_time DESC");
    const latestWaterByLoc = {};
    for (const w of waters) if (!latestWaterByLoc[w.location]) latestWaterByLoc[w.location] = w;
    const aiPayload = reports.map(r => ({
      id: r.id,
      location: r.location,
      symptoms: r.symptoms,
      turbidity: r.turbidity ?? (latestWaterByLoc[r.location]?.turbidity ?? 0),
      pH: r.pH ?? (latestWaterByLoc[r.location]?.pH ?? 7),
      bacteria_count: r.bacteria_count ?? (latestWaterByLoc[r.location]?.bacteria_count ?? 0),
      report_time: r.report_time,
    }));
    const aiRes = await axios.post(process.env.AI_URL || 'http://127.0.0.1:5000/analyze', aiPayload, { timeout: 5000 });
    res.json(aiRes.data);
  } catch (e) {
    console.warn('AI analyze failed:', e.message);
    res.status(502).json({ message: 'AI service unavailable', error: e.message });
  }
});

// Start server
app.listen(PORT, () => console.log(`🚀 Server running at http://localhost:${PORT}`));
