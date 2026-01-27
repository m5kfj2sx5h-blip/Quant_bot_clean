#!/bin/bash

echo "🚀 Starting Integrated System Flow..."
echo "📦 Installing dependencies..."
pip install -r requirements.txt

echo "🔧 Starting Data Hub and Intelligence Engine..."
python system_orchestrator.py &

echo "🌐 Starting Mission Control Dashboard..."
streamlit run dashboard.py --server.port 8501 --server.address 0.0.0.0 &

echo "✅ System components started!"
echo "📊 Dashboard: http://localhost:8501"
echo "📈 System logs: Check terminal output"
echo ""
echo "🛑 To stop: Press Ctrl+C and run: pkill -f 'python\|streamlit'"