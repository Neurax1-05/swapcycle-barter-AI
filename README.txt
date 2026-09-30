Copy everything in this folder into SwapCycle_Checkpoint_Package (overwrite when asked).
Then, from that folder:
  pytest tests -v
  python sync_functions.py
  firebase functions:secrets:set OPENROUTER_API_KEY
  firebase deploy --only functions:run_matching_on_preference_create
