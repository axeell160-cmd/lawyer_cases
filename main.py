"""
Улучшенное API для реестра судебных дел юриста
"""
from datetime import date, datetime
from enum import Enum
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Query, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import create_engine, Column, Integer, String, Date, DateTime, Text, Boolean
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from sqlalchemy.sql import func

# ==================== База данных ====================
DATABASE_URL = "sqlite:///./cases.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class CaseStatus(str, Enum):
    open = "open"           # В производстве
    in_court = "in_court"   # В суде
    appeal = "appeal"       # Обжалование
    suspended = "suspended" # Приостановлено
    closed = "closed"       # Завершено

class CaseModel(Base):
    __tablename__ = "cases"
    
    id = Column(Integer, primary_key=True, index=True)
    case_number = Column(String, unique=True, index=True, nullable=False)
    client_name = Column(String, nullable=False, index=True)
    opposing_party = Column(String, nullable=True)
    court_name = Column(String, nullable=True)
    judge_name = Column(String, nullable=True)          # Новый
    claim_amount = Column(Integer, nullable=True)       # Сумма иска (в рублях)
    status = Column(String, default=CaseStatus.open.value)
    next_hearing_date = Column(Date, nullable=True, index=True)
    description = Column(Text, nullable=True)
    responsible = Column(String, nullable=True)         # Ответственный юрист
    is_deleted = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ==================== Pydantic схемы ====================
class CaseBase(BaseModel):
    case_number: str = Field(..., min_length=3, description="Номер судебного дела")
    client_name: str = Field(..., min_length=2)
    opposing_party: Optional[str] = None
    court_name: Optional[str] = None
    judge_name: Optional[str] = None
    claim_amount: Optional[int] = Field(None, ge=0)
    status: CaseStatus = CaseStatus.open
    next_hearing_date: Optional[date] = None
    description: Optional[str] = None
    responsible: Optional[str] = None

    @field_validator('case_number')
    @classmethod
    def uppercase_case_number(cls, v: str):
        return v.strip().upper()

class CaseCreate(CaseBase):
    pass

class CaseUpdate(BaseModel):
    case_number: Optional[str] = None
    client_name: Optional[str] = None
    opposing_party: Optional[str] = None
    court_name: Optional[str] = None
    judge_name: Optional[str] = None
    claim_amount: Optional[int] = None
    status: Optional[CaseStatus] = None
    next_hearing_date: Optional[date] = None
    description: Optional[str] = None
    responsible: Optional[str] = None

class CaseOut(CaseBase):
    id: int
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True

class CasesResponse(BaseModel):
    items: List[CaseOut]
    total: int
    page: int
    size: int

class DashboardStats(BaseModel):
    total_cases: int
    open_cases: int
    next_hearings_this_week: int
    upcoming_hearings: List[CaseOut]

# ==================== FastAPI ====================
app = FastAPI(
    title="Реестр судебных дел",
    description="Улучшенное API для управления судебными делами юриста",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # В продакшене заменить на конкретные домены
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==================== Эндпоинты ====================
@app.post("/cases", response_model=CaseOut, summary="Создать новое дело")
def create_case(case: CaseCreate, db: Session = Depends(get_db)):
    existing = db.query(CaseModel).filter(
        CaseModel.case_number == case.case_number,
        CaseModel.is_deleted == False
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Дело с таким номером уже существует")
    
    db_case = CaseModel(**case.model_dump())
    db.add(db_case)
    db.commit()
    db.refresh(db_case)
    return db_case

@app.get("/cases", response_model=CasesResponse, summary="Список дел с фильтрами и пагинацией")
def list_cases(
    status: Optional[List[CaseStatus]] = Query(None),
    client_name: Optional[str] = Query(None),
    case_number: Optional[str] = Query(None),
    next_hearing_from: Optional[date] = None,
    next_hearing_to: Optional[date] = None,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    query = db.query(CaseModel).filter(CaseModel.is_deleted == False)
    
    if status:
        query = query.filter(CaseModel.status.in_([s.value for s in status]))
    if client_name:
        query = query.filter(CaseModel.client_name.ilike(f"%{client_name}%"))
    if case_number:
        query = query.filter(CaseModel.case_number.ilike(f"%{case_number}%"))
    if next_hearing_from:
        query = query.filter(CaseModel.next_hearing_date >= next_hearing_from)
    if next_hearing_to:
        query = query.filter(CaseModel.next_hearing_date <= next_hearing_to)
    
    total = query.count()
    items = query.order_by(
        CaseModel.next_hearing_date.is_(None), 
        CaseModel.next_hearing_date
    ).offset((page-1)*size).limit(size).all()
    
    return {"items": items, "total": total, "page": page, "size": size}

@app.get("/cases/{case_id}", response_model=CaseOut)
def get_case(case_id: int, db: Session = Depends(get_db)):
    db_case = db.query(CaseModel).filter(
        CaseModel.id == case_id, 
        CaseModel.is_deleted == False
    ).first()
    if not db_case:
        raise HTTPException(status_code=404, detail="Дело не найдено")
    return db_case

@app.put("/cases/{case_id}", response_model=CaseOut)
def update_case(case_id: int, case: CaseUpdate, db: Session = Depends(get_db)):
    db_case = db.query(CaseModel).filter(
        CaseModel.id == case_id, 
        CaseModel.is_deleted == False
    ).first()
    if not db_case:
        raise HTTPException(status_code=404, detail="Дело не найдено")
    
    update_data = case.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_case, field, value)
    
    db.commit()
    db.refresh(db_case)
    return db_case

@app.delete("/cases/{case_id}")
def delete_case(case_id: int, db: Session = Depends(get_db)):
    db_case = db.query(CaseModel).filter(CaseModel.id == case_id).first()
    if not db_case:
        raise HTTPException(status_code=404, detail="Дело не найдено")
    db_case.is_deleted = True
    db.commit()
    return {"detail": "Дело перемещено в архив"}

@app.get("/stats", response_model=DashboardStats, summary="Статистика для дашборда")
def get_stats(db: Session = Depends(get_db)):
    total = db.query(CaseModel).filter(CaseModel.is_deleted == False).count()
    open_cases = db.query(CaseModel).filter(
        CaseModel.status != CaseStatus.closed.value,
        CaseModel.is_deleted == False
    ).count()
    
    # Можно добавить больше статистики
    upcoming = db.query(CaseModel).filter(
        CaseModel.next_hearing_date.isnot(None),
        CaseModel.is_deleted == False
    ).order_by(CaseModel.next_hearing_date).limit(5).all()
    
    return {
        "total_cases": total,
        "open_cases": open_cases,
        "next_hearings_this_week": 0,  # Можно реализовать
        "upcoming_hearings": upcoming
    }

@app.get("/", summary="Проверка API")
def root():
    return {"status": "ok", "service": "Реестр судебных дел v2.0"}
