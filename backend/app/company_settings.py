from copy import deepcopy
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import base64
import re

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SettingsModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class GeneralSettings(SettingsModel):
    companyName: str = Field(default="", max_length=120)
    logo: str = ""
    timezone: str = "Asia/Almaty"
    shiftEnd: str = "00:00"
    currency: Literal["KGS", "KZT", "RUB", "USD", "EUR"] = "KGS"
    language: Literal["ru"] = "ru"
    floorPlan: bool = False
    fractional: bool = False
    roundTotal: bool = False
    servicePercent: int = Field(default=0, ge=0, le=30)
    serviceDefault: bool = False

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value):
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("Неизвестный часовой пояс")
        return value

    @field_validator("shiftEnd")
    @classmethod
    def valid_time(cls, value):
        if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value):
            raise ValueError("Укажите время в формате ЧЧ:ММ")
        return value

    @field_validator("logo")
    @classmethod
    def valid_logo(cls, value):
        if not value:
            return value
        match = re.fullmatch(r"data:image/(png|jpeg|webp|gif);base64,([A-Za-z0-9+/=]+)", value)
        if not match:
            raise ValueError("Логотип должен быть JPEG, PNG, WebP или GIF")
        try:
            data = base64.b64decode(match[2], validate=True)
        except ValueError:
            raise ValueError("Повреждённый файл логотипа")
        signatures = {"png": b"\x89PNG\r\n\x1a\n", "jpeg": b"\xff\xd8\xff", "gif": b"GIF8", "webp": b"RIFF"}
        valid_signature = data.startswith(signatures[match[1]])
        if match[1] == "webp":
            valid_signature = valid_signature and len(data) >= 12 and data[8:12] == b"WEBP"
        if len(data) > 5 * 1024 * 1024 or not valid_signature:
            raise ValueError("Проверьте формат и размер логотипа (до 5 МБ)")
        return value


class OrdersSettings(SettingsModel):
    dineIn: bool = True
    takeaway: bool = True
    defaultType: Literal["dine-in", "takeaway"] = "dine-in"
    preparationMinutes: int = Field(default=20, ge=1, le=240)
    requireCustomer: bool = False
    requireComment: bool = False
    tables: list[str] = Field(default_factory=lambda: ["Стол 1", "Стол 2", "Стол 3", "Стол 4"], max_length=100)

    @field_validator("tables")
    @classmethod
    def valid_tables(cls, value):
        if any(not name.strip() or len(name) > 60 for name in value) or len(set(value)) != len(value):
            raise ValueError("Названия столов должны быть непустыми и не повторяться")
        return value


class DeliveryArea(SettingsModel):
    name: str = Field(min_length=1, max_length=80)
    cost: float = Field(default=0, ge=0, le=100000)
    freeFrom: float = Field(default=0, ge=0, le=10000000)
    minutes: int = Field(default=60, ge=1, le=1440)


class DeliverySettings(SettingsModel):
    enabled: bool = False
    useReadyStatus: bool = True
    useDeliveredStatus: bool = True
    areas: list[DeliveryArea] = Field(default_factory=list, max_length=50)

    @field_validator("areas")
    @classmethod
    def unique_areas(cls, value):
        names = [area.name.strip() for area in value]
        if any(not name for name in names) or len(names) != len(set(names)):
            raise ValueError("Названия районов должны быть непустыми и не повторяться")
        return value


class SecuritySettings(SettingsModel):
    deleteOrder: Literal["never", "always"] = "never"
    discount: Literal["never", "always"] = "never"
    reports: Literal["never", "always"] = "never"
    closeReceipt: Literal["never", "always"] = "never"
    addCustomer: Literal["never", "always"] = "never"
    orderHistory: Literal["never", "always"] = "never"
    addSupply: Literal["never", "always"] = "never"
    refund: Literal["never", "always"] = "never"


class ReceiptSettings(SettingsModel):
    autoPrint: bool = False
    showNumber: bool = True
    showCashier: bool = True
    showComment: bool = False
    showCustomer: bool = False
    showWifi: bool = False
    wifiName: str = Field(default="", max_length=120)
    wifiPassword: str = Field(default="", max_length=120)
    showAddress: bool = False
    city: str = Field(default="", max_length=100)
    address: str = Field(default="", max_length=250)
    phone: str = Field(default="", max_length=50)
    nameSource: Literal["company", "branch"] = "company"
    language: Literal["ru", "en"] = "ru"
    footer: str = Field(default="Спасибо за покупку!", max_length=500)


MODELS = {"general": GeneralSettings, "orders": OrdersSettings, "delivery": DeliverySettings,
          "security": SecuritySettings, "receipt": ReceiptSettings}


def company_settings(state):
    saved = state.get("companySettings", {})
    return {name: {**model().model_dump(), **deepcopy(saved.get(name, {}))} for name, model in MODELS.items()}


def validate_settings_section(section, values):
    if section not in MODELS:
        raise ValueError("Неизвестный раздел настроек")
    output = MODELS[section].model_validate(values).model_dump()
    if section == "orders":
        if not output["dineIn"] and not output["takeaway"]:
            raise ValueError("Оставьте хотя бы один тип заказа")
        if not output["dineIn" if output["defaultType"] == "dine-in" else "takeaway"]:
            raise ValueError("Тип заказа по умолчанию должен быть включён")
    return output


def require_manager(state, user, key):
    if company_settings(state)["security"].get(key) != "always":
        return
    if user.get("role") == "owner" or user.get("staff_role") in {"branch_manager", "hall_admin"}:
        return
    raise PermissionError("Для этого действия войдите под PIN управляющего")
