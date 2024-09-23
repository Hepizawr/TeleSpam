from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from loguru import logger
import config

logger.info(F"URL IS {config.DATABASE_URL}")
engine = create_engine(config.DATABASE_URL, pool_pre_ping=True, pool_recycle=300)
Session = sessionmaker(bind=engine, expire_on_commit=False)
session = Session()
