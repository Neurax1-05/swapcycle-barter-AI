# SwapCycle checkpoint package

Install:
py -m pip install -r requirements.txt

AI setup (PowerShell):
$env:OPENROUTER_API_KEY="YOUR_NEW_ROTATED_KEY"
$env:OPENROUTER_MODEL="openai/gpt-4o-mini"

Or copy .env.example to .env.

Run matching + visualizations + benchmark:
py bgcc_prototype.py

Run live AI normalization:
py ai_preference.py

Run end-to-end offline:
py end_to_end_demo.py --offline

Run end-to-end with live AI:
py end_to_end_demo.py

The real key should NOT be committed to source control.
