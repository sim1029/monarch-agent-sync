"""Save a Monarch Money session from a browser token."""
import pickle

token = input("Paste your Monarch token: ").strip()
with open(".monarch_session", "wb") as f:
    pickle.dump({"token": token}, f)
print("Session saved to .monarch_session")
