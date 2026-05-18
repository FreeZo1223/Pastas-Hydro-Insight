
import asyncio
import os
import sys
from pathlib import Path
from datetime import datetime, timezone

# Add repo root to sys.path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# --- PROJ fix ---
try:
    import pyproj
    import os
    from pathlib import Path
    _pd = pyproj.datadir.get_data_dir()
    if _pd:
        os.environ["PROJ_DATA"] = _pd
        os.environ["PROJ_LIB"] = _pd
except Exception:
    pass
# --- End PROJ fix ---

from lesa.domain.aoi import AOI
from lesa.plugins._registry import get_registry
from lesa.session.local_store import LocalSessionStore
from lesa.session.state import SessionState, SkippedPlugin
from lesa.agent.runner import PluginRunner

async def main():
    # 1. Setup paths
    aoi_path = Path(r"C:\GIS_Projecten\Prive_projecten\Zeeland_NB\data\aoi_duifhuis.geojson")
    sessions_dir = ROOT / "sessions"
    
    # 2. Load AOI
    aoi = AOI.from_geojson_file(aoi_path)
    print(f"AOI geladen: {aoi.name or 'Duifhuis'}")
    
    # 3. Create Session
    store = LocalSessionStore(base_dir=sessions_dir)
    session = SessionState(
        project_name="Duifhuis LESA Run",
        aoi=aoi,
        scale_level=2,
        landscape_type="zandlandschap"
    )
    store.save(session)
    print(f"Sessie aangemaakt: {session.session_id}")
    
    # 4. Initialize Runner
    registry = get_registry()
    runner = PluginRunner(registry=registry, store=store)
    
    # 5. Skip Rangorde 1 (Geologie - no plugin yet)
    session.skipped_plugins.append(
        SkippedPlugin(
            plugin_id="geologie",
            rangorde_position=1,
            reason="Geen geologie-plugin beschikbaar in registry; sla over naar geomorfologie."
        )
    )
    print("Rangorde 1 overgeslagen.")
    
    # 6. Run Plugins
    plugins_to_run = ["geomorfologie_ahn", "bodem_bro", "grondwater_pastas"]
    
    import pyproj
    print(f"DEBUG: pyproj data dir: {pyproj.datadir.get_data_dir()}")
    print(f"DEBUG: PROJ_DATA env: {os.environ.get('PROJ_DATA')}")
    
    for pid in plugins_to_run:
        print(f"\n--- Starten plugin: {pid} ---")
        # Voor geomorfologie en bodem gebruiken we standaard parameters (lege dict)
        # Voor grondwater_pastas ook
        result = await runner.run(session, pid, {})
        
        if result.ok:
            print(f"Vinkje! {pid} succesvol afgerond.")
            print(f"Samenvatting: {result.outputs.summary}")
            print(f"Artifacts: {list(result.outputs.artifacts.keys())}")
        else:
            print(f"FOUT bij {pid}: {result.error or result.skipped_reason}")
            if not result.ok:
                # Stop de run bij een harde fout om rangorde-integriteit te bewaken
                break

    print(f"\nLESA run voltooid voor Duifhuis.")
    print(f"Resultaten te vinden in: {sessions_dir / session.session_id}")

if __name__ == "__main__":
    asyncio.run(main())
