from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime

Base = declarative_base()

class Trade(Base):
    __tablename__ = 'trades'
    
    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    symbol = Column(String)
    contract_type = Column(String)  # 'PUT' or 'CALL'
    strike = Column(Float)
    expiry = Column(DateTime)
    quantity = Column(Integer)
    price = Column(Float)
    commission = Column(Float)
    
class Database:
    def __init__(self, db_path='sqlite:///trades.db'):
        self.engine = create_engine(db_path)
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        
    def add_trade(self, trade_data):
        session = self.Session()
        try:
            trade = Trade(**trade_data)
            session.add(trade)
            session.commit()
        finally:
            session.close()
            
    def get_trades(self, start_date=None, end_date=None):
        session = self.Session()
        try:
            query = session.query(Trade)
            if start_date:
                query = query.filter(Trade.timestamp >= start_date)
            if end_date:
                query = query.filter(Trade.timestamp <= end_date)
            return query.all()
        finally:
            session.close() 