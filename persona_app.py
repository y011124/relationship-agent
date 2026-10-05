"""Run the Persona AI beta; existing web_app.py remains the legacy local entry."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).parent/'src'))
from relationship_agent.beta.app import main
if __name__=='__main__':main()
