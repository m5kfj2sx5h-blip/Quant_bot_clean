Frontend Guidelines – UI/UX Rules
Status: Minimal Frontend <- needs attention!!
The bot is primarily backend/headless. Any UI (dashboard.py, mini_dashboard.py) is utilitarian monitoring only with no rich interactive app.
we need that!!


Core Principles

Simplicity: Clean, text-heavy display. Avoids visual clutter, but severly lacking functionality.
Consistency: Use fixed-width BORDERLESS tables for balances, positions, logs.
Readability: use same font and colors and theme, clear section headers (need small titles as to not waste space over titles!), color-coded status (green=healthy, yellow=warning, red=error).
Real-Time: Auto-refresh every 5–10 seconds.

Components (If Implemented)

Dashboard Layout:
Top: Current mode (BTC/GOLD), total USD capital, drift %.
Middle: Exchange balances table, staking positions (coin, APY, exchange), needs to focus on opportunities.
Bottom: Recent trades log, active bot status.

Colors: Minimal – green (profit), red (loss), blue (neutral).
Typography: Single font (system default or monospace); headings bold.
Responsiveness: Desktop-only (fixed width).

Rules

Need user input forms – currently read-only monitoring!!!
All data fetched live (same as backend).
Error states clearly highlighted with warnings.

Expand UI, adopt a full design system like Material or Tailwind for future consistency.
