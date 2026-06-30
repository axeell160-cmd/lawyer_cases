"""
API для реестра судебных дел юриста.
Минимальный набор функций: создание, просмотр, обновление, удаление дел,
а также фильтрация по статусу и поиск по клиенту/номеру дела.

Запуск:
    pip install fastapi uvicorn sqlalchemy --break-system-packages
    uvicorn main:app --reload

Документация (Swagger) будет доступна на http://127.0.0.1:8000/docs
"""

from datetime import date, datetime
from enum import Enum
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, Column, Integer, String, Date, DateTime, Text
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from fastapi.params import Depends


# ---------- База данных ----------

DATABASE_URL = "sqlite:///./cases.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class CaseStatus(str, Enum):
    open = "open"               # в производстве
    in_court = "in_court"       # рассматривается судом
    appeal = "appeal"           # обжалование
    suspended = "suspended"     # приостановлено
    closed = "closed"           # завершено


class CaseModel(Base):
    __tablename__ = "cases"

    id = Column(Integer, primary_key=True, index=True)
    case_number = Column(String, unique=True, index=True, nullable=False)  # номер дела
    client_name = Column(String, nullable=False)                          # клиент
    opposing_party = Column(String, nullable=True)                        # ответчик/истец
    court_name = Column(String, nullable=True)                            # суд
    status = Column(String, default=CaseStatus.open.value)                # статус
    next_hearing_date = Column(Date, nullable=True)                       # дата следующего заседания
    description = Column(Text, nullable=True)                             # суть дела
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ---------- Pydantic-схемы ----------

class CaseBase(BaseModel):
    case_number: str = Field(..., description="Номер судебного дела")
    client_name: str = Field(..., description="ФИО / название клиента")
    opposing_party: Optional[str] = Field(None, description="Противоположная сторона")
    court_name: Optional[str] = Field(None, description="Наименование суда")
    status: CaseStatus = Field(CaseStatus.open, description="Статус дела")
    next_hearing_date: Optional[date] = Field(None, description="Дата следующего заседания")
    description: Optional[str] = Field(None, description="Краткое описание сути дела")


class CaseCreate(CaseBase):
    pass


class CaseUpdate(BaseModel):
    case_number: Optional[str] = None
    client_name: Optional[str] = None
    opposing_party: Optional[str] = None
    court_name: Optional[str] = None
    status: Optional[CaseStatus] = None
    next_hearing_date: Optional[date] = None
    description: Optional[str] = None


class CaseOut(CaseBase):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ---------- Приложение ----------

app = FastAPI(
    title="Реестр судебных дел",
    description="Минимальное API для ведения реестра судебных дел юриста",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/cases", response_model=CaseOut, summary="Добавить новое дело")
def create_case(case: CaseCreate, db: Session = Depends(get_db)):
    existing = db.query(CaseModel).filter(CaseModel.case_number == case.case_number).first()
    if existing:
        raise HTTPException(status_code=400, detail="Дело с таким номером уже существует")
    db_case = CaseModel(**case.model_dump())
    db.add(db_case)
    db.commit()
    db.refresh(db_case)
    return db_case


@app.get("/cases", response_model=List[CaseOut], summary="Список дел (с фильтрами)")
def list_cases(
    status: Optional[CaseStatus] = Query(None, description="Фильтр по статусу"),
    client_name: Optional[str] = Query(None, description="Поиск по клиенту (частичное совпадение)"),
    db: Session = Depends(get_db),
):
    query = db.query(CaseModel)
    if status:
        query = query.filter(CaseModel.status == status.value)
    if client_name:
        query = query.filter(CaseModel.client_name.ilike(f"%{client_name}%"))
    return query.order_by(CaseModel.next_hearing_date.is_(None), CaseModel.next_hearing_date).all()


@app.get("/cases/{case_id}", response_model=CaseOut, summary="Получить дело по ID")
def get_case(case_id: int, db: Session = Depends(get_db)):
    db_case = db.query(CaseModel).filter(CaseModel.id == case_id).first()
    if not db_case:
        raise HTTPException(status_code=404, detail="Дело не найдено")
    return db_case


@app.put("/cases/{case_id}", response_model=CaseOut, summary="Обновить дело")
def update_case(case_id: int, case: CaseUpdate, db: Session = Depends(get_db)):
    db_case = db.query(CaseModel).filter(CaseModel.id == case_id).first()
    if not db_case:
        raise HTTPException(status_code=404, detail="Дело не найдено")
    for field, value in case.model_dump(exclude_unset=True).items():
        setattr(db_case, field, value)
    db.commit()
    db.refresh(db_case)
    return db_case


@app.delete("/cases/{case_id}", summary="Удалить дело")
def delete_case(case_id: int, db: Session = Depends(get_db)):
    db_case = db.query(CaseModel).filter(CaseModel.id == case_id).first()
    if not db_case:
        raise HTTPException(status_code=404, detail="Дело не найдено")
    db.delete(db_case)
    db.commit()
    return {"detail": "Дело удалено"}


@app.get("/", summary="Проверка работоспособности")
def root():
    return {"status": "ok", "service": "Реестр судебных дел"}
