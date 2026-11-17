import os,json
from pathlib import Path
APP_DIR=Path(os.environ.get('APP_DIR','/app'))
CONFIG=json.loads((APP_DIR/'project.json').read_text())
DATABASE_URL=os.environ['DATABASE_URL']
REDIS_URL=os.getenv('REDIS_URL','redis://redis:6379/0')
SECRET=os.environ['JWT_SECRET']
