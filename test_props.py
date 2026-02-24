import hydropandas as hpd

bro_id = "GMW000000069526"
try:
    obs = hpd.GroundwaterObs.from_bro(bro_id, tube_nr=1)
    print(f"Prop x: {obs.x}")
    print(f"Prop y: {obs.y}")
    print(f"Prop name: {obs.name}")
    print(f"Prop ground_level: {obs.ground_level}")
except Exception as e:
    print(f"ERROR: {e}")
