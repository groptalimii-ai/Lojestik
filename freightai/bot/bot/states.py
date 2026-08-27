from aiogram.fsm.state import State, StatesGroup


class NewLoadFlow(StatesGroup):
    waiting_for_text = State()
    confirming = State()
    asking_missing_field = State()


class RegisterCarrierFlow(StatesGroup):
    waiting_for_company_name = State()
    waiting_for_phone = State()


class PricingRequestFlow(StatesGroup):
    waiting_for_origin = State()
    waiting_for_destination = State()
    waiting_for_truck_type = State()
    waiting_for_weight = State()
    waiting_for_price_opt = State()


class AddTruckFlow(StatesGroup):
    waiting_for_phone_lookup = State()   # used when entering via /mytrucks
    waiting_for_head_type = State()
    waiting_for_trailer_type = State()
    waiting_for_max_weight = State()
    waiting_for_current_location = State()
    waiting_for_routes = State()
    waiting_for_available_date = State()
    waiting_for_price = State()
    waiting_for_return_load = State()
