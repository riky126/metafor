
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

# Watch for changes
# unsubscribe_counter = container.watch(counter_provider, counter_listener)
# unsubscribe_data = container.watch(data_provider, data_listener)

# # Get the current counter value
# initial_count = container.get(counter_provider)

# Update the counter value
# container.set(counter_provider, 10)

# Wait for the FutureProvider to complete
# async def run():
#     initial_data = container.get(data_provider)
#     print(f"Initial data: {initial_data}") # the future result
#     data = await container.get_future(data_provider)
#     print(f"Data fetched: {data}")

# # Clean up watchers
# unsubscribe_counter()
# unsubscribe_data()

# if __name__ == "__app__":
#     asyncio.run(run())
