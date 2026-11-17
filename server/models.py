from sqlalchemy import create_engine, Column, Integer, String, Float
from sqlalchemy.orm import declarative_base, sessionmaker
import os

# Emulación de base de datos local (similar a Azure SQL)
DATABASE_URL = "sqlite:///./storage/incidentes.db"

# Asegurar que el directorio storage exista
os.makedirs('./storage', exist_ok=True)

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class Incidente(Base):
    __tablename__ = "incidentes"

    id = Column(Integer, primary_key=True, index=True)
    vehiculo_id = Column(String, index=True)
    evento = Column(String)
    duracion_seg = Column(Float)
    confianza_custom = Column(Float)
    evidencia_url = Column(String)

# Crear la tabla si no existe
Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()