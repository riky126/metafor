# Define a StateContainer instance
import asyncio
from metafor.store import FutureProvider, ProviderContainer, StateProvider

container = ProviderContainer()

# Define a state provider
counter_provider = StateProvider(0, name="counter")

app_provider = StateProvider({"auth_user": None}, name="app_state")

# Define a function to create a future for FutureProvider
async def fetch_data(container):
    print("Fetching data...")
    await asyncio.sleep(2)  # Simulate some work
    return {"data": "Data from async call"}

# Define a FutureProvider
data_provider = FutureProvider(fetch_data, name='data_provider')