from decimal import Decimal
from enum import Enum
from typing import Annotated, Any

from pydantic import BaseModel, Field, StringConstraints, model_validator


NonEmptyText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
ItemId = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9._:-]+$")]
PositiveQuantity = Annotated[Decimal, Field(gt=0, max_digits=14, decimal_places=4)]
Money = Annotated[Decimal, Field(ge=0, max_digits=14, decimal_places=4)]
PositiveWeight = Annotated[Decimal, Field(gt=0, max_digits=14, decimal_places=3)]


class ItemType(str, Enum):
    ingredient = "ingredient"
    preparation = "preparation"
    product = "product"


class CatalogItemCreate(BaseModel):
    id: ItemId | None = None
    item_type: ItemType
    name: NonEmptyText
    category: NonEmptyText
    unit: NonEmptyText
    purchase_cost: Money = Decimal("0")
    sale_price: Money | None = None


class ComponentInput(BaseModel):
    item_id: ItemId
    gross_quantity: PositiveQuantity
    net_quantity: PositiveQuantity

    @model_validator(mode="after")
    def validate_quantities(self) -> "ComponentInput":
        if self.net_quantity > self.gross_quantity:
            raise ValueError("Нетто не может быть больше брутто")
        return self


class TechnicalCardCreate(BaseModel):
    output_item: CatalogItemCreate
    yield_quantity: PositiveQuantity
    yield_weight_grams: PositiveWeight | None = None
    station: NonEmptyText
    components: Annotated[list[ComponentInput], Field(min_length=1, max_length=100)]

    @model_validator(mode="after")
    def validate_card(self) -> "TechnicalCardCreate":
        if self.output_item.item_type == ItemType.ingredient:
            raise ValueError("Техкарта может выпускать блюдо или полуфабрикат, но не ингредиент")
        component_ids = [component.item_id for component in self.components]
        if len(component_ids) != len(set(component_ids)):
            raise ValueError("Одна позиция не может повторяться в составе техкарты")
        if self.output_item.id and self.output_item.id in component_ids:
            raise ValueError("Позиция не может входить в собственную техкарту")
        return self


class TechnicalCardUpdate(BaseModel):
    version: Annotated[int, Field(gt=0)]
    name: NonEmptyText
    category: NonEmptyText
    unit: NonEmptyText
    purchase_cost: Money = Decimal("0")
    sale_price: Money | None = None
    yield_quantity: PositiveQuantity
    yield_weight_grams: PositiveWeight | None = None
    station: NonEmptyText
    components: Annotated[list[ComponentInput], Field(min_length=1, max_length=100)]

    @model_validator(mode="after")
    def validate_components(self) -> "TechnicalCardUpdate":
        component_ids = [component.item_id for component in self.components]
        if len(component_ids) != len(set(component_ids)):
            raise ValueError("Одна позиция не может повторяться в составе техкарты")
        return self


class LoginInput(BaseModel):
    login: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=64)]
    password: Annotated[str, StringConstraints(min_length=8, max_length=200)]
    register_id: Annotated[int, Field(gt=0)] | None = None


class WorkspaceActionInput(BaseModel):
    action: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=80)]
    payload: dict[str, Any] = Field(default_factory=dict)


TenantSlug = Annotated[str, StringConstraints(strip_whitespace=True, to_lower=True, min_length=3, max_length=48, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")]
AccountLogin = Annotated[str, StringConstraints(strip_whitespace=True, to_lower=True, min_length=3, max_length=200, pattern=r"^[a-zA-Z0-9._@+-]+$")]
ContactEmail = Annotated[str, StringConstraints(strip_whitespace=True, to_lower=True, min_length=5, max_length=200, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")]
PhoneText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=40)]
ClockTime = Annotated[str, StringConstraints(pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")]
CashierPin = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^\d{4}$")]


class StaffRole(str, Enum):
    branch_manager = "branch_manager"
    hall_admin = "hall_admin"
    waiter = "waiter"
    storekeeper = "storekeeper"
    production = "production"
    marketer = "marketer"
    cashier = "cashier"


class EmployeePermissions(BaseModel):
    posAccess: bool = False
    posRefunds: bool = False
    posCash: bool = False
    posSupply: bool = False
    reports: bool = False
    menu: bool = False
    inventory: bool = False
    production: bool = False
    finance: bool = False
    employees: bool = False
    registers: bool = False
    settings: bool = False


class EmployeeCreate(BaseModel):
    display_name: NonEmptyText
    phone: Annotated[str, StringConstraints(strip_whitespace=True, max_length=40)] = ""
    branch_id: ItemId
    staff_role: StaffRole
    login: AccountLogin | None = None
    password: Annotated[str, StringConstraints(min_length=8, max_length=200)] | None = None
    pin: CashierPin | None = None
    permissions: EmployeePermissions | None = None


class EmployeeUpdate(BaseModel):
    display_name: NonEmptyText
    phone: Annotated[str, StringConstraints(strip_whitespace=True, max_length=40)] = ""
    branch_id: ItemId
    staff_role: StaffRole
    login: AccountLogin | None = None
    password: Annotated[str, StringConstraints(min_length=8, max_length=200)] | None = None
    pin: CashierPin | None = None
    is_active: bool = True
    permissions: EmployeePermissions | None = None


class PosUnlockInput(BaseModel):
    employee_id: Annotated[int, Field(gt=0)] | None = None  # Legacy clients; identity is always resolved by PIN.
    pin: CashierPin


class PosRegisterCreate(BaseModel):
    name: NonEmptyText
    branch_id: ItemId
    password: Annotated[str, StringConstraints(min_length=8, max_length=200)]
    login: Annotated[AccountLogin, Field(max_length=64)] | None = None


class PosRegisterUpdate(BaseModel):
    name: NonEmptyText
    branch_id: ItemId
    password: Annotated[str, StringConstraints(min_length=8, max_length=200)] | None = None
    is_active: bool = True
    login: Annotated[AccountLogin, Field(max_length=64)] | None = None


class PosShiftOpen(BaseModel):
    opening_cash: Money = Decimal("0")


class PosShiftClose(BaseModel):
    closing_cash: Money
    stock_counts: list[dict[str, Any]] = Field(default_factory=list)
    stock_confirmed: bool = False
    state_version: int | None = None


class TenantCreate(BaseModel):
    name: NonEmptyText
    slug: TenantSlug
    owner_name: NonEmptyText
    email: ContactEmail
    phone: PhoneText
    owner_login: AccountLogin | None = None
    owner_password: Annotated[str, StringConstraints(min_length=12, max_length=200)]
    business_status: Annotated[str, StringConstraints(pattern=r"^(operating|opening|learning)$")] = "operating"
    business_type: Annotated[str, StringConstraints(pattern=r"^(canteen|cafe|restaurant|fast_food|bakery|shop|other)$")] = "canteen"
    service_modes: Annotated[list[Annotated[str, StringConstraints(pattern=r"^(counter|tables|takeaway|delivery)$")]], Field(min_length=1, max_length=4)]
    employee_range: Annotated[str, StringConstraints(pattern=r"^(1-3|4-9|10-19|20\+)$")] = "1-3"
    location_name: NonEmptyText
    location_address: NonEmptyText
    location_open_time: ClockTime = "08:00"
    location_close_time: ClockTime = "20:00"
    register_password: Annotated[str, StringConstraints(min_length=8, max_length=200)]
    plan_code: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=32)] = "canteen"
    max_branches: Annotated[int, Field(ge=1, le=1000)] = 3
    trial_days: Annotated[int, Field(ge=0, le=365)] = 14

    @model_validator(mode="after")
    def default_owner_login_to_email(self) -> "TenantCreate":
        if self.owner_login is None:
            self.owner_login = self.email
        return self


class TenantDelete(BaseModel):
    confirmation_name: str = Field(min_length=1, max_length=200)


class TenantUpdate(BaseModel):
    name: NonEmptyText | None = None
    email: ContactEmail | None = None
    phone: PhoneText | None = None
    business_status: Annotated[str, StringConstraints(pattern=r"^(operating|opening|learning)$")] | None = None
    business_type: Annotated[str, StringConstraints(pattern=r"^(canteen|cafe|restaurant|fast_food|bakery|shop|other)$")] | None = None
    service_modes: Annotated[list[Annotated[str, StringConstraints(pattern=r"^(counter|tables|takeaway|delivery)$")]], Field(min_length=1, max_length=4)] | None = None
    employee_range: Annotated[str, StringConstraints(pattern=r"^(1-3|4-9|10-19|20\+)$")] | None = None
    status: Annotated[str, StringConstraints(pattern=r"^(active|suspended|archived)$")] | None = None
    plan_code: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=32)] | None = None
    subscription_status: Annotated[str, StringConstraints(pattern=r"^(trialing|active|past_due|canceled)$")] | None = None
    max_branches: Annotated[int, Field(ge=1, le=1000)] | None = None


class TenantOwnerAccessUpdate(BaseModel):
    owner_name: NonEmptyText
    owner_login: AccountLogin
    owner_password: Annotated[str, StringConstraints(min_length=12, max_length=200)] | None = None


class PlanPriceUpdate(BaseModel):
    monthly_price: Annotated[Decimal, Field(ge=0, le=9999999999, max_digits=12, decimal_places=2)]
    annual_price: Annotated[Decimal, Field(ge=0, le=9999999999, max_digits=12, decimal_places=2)] | None = None
