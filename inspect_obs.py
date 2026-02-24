import hydropandas as hpd

bro_id = "GMW000000069526"
try:
    obs = hpd.GroundwaterObs.from_bro(bro_id, tube_nr=1)
    print(f"Type: {type(obs)}")
    print("Attributes/Methods:", dir(obs))
    # Try more robust metadata access
    if hasattr(obs, 'metadata'):
        print("Metadata attribute found.")
    else:
        print("Metadata attribute NOT found.")
    
    # Check if it's a DataFrame and if metadata is stored elsewhere
    if isinstance(obs, hpd.observation.Obs):
        print("Is a hydropandas Obs object.")
except Exception as e:
    print(f"ERROR: {e}")
