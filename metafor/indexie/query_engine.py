
import json
from js import console, Promise
from pyodide.ffi import create_proxy, to_js
from .support import _to_js_obj, IndexedDBError
from .js_code import JS_FAST_CURSOR_CODE

class QueryEngine:
    def __init__(self, db: 'Indexie'):
        self.db = db
        # We'll compile the JS function once if possible, or eval it when needed if context is tricky.
        import js
        self._fast_cursor_js = js.eval(JS_FAST_CURSOR_CODE)

    # --- Write Operations (Consolidated) ---
    
    async def add(self, table_name, item, key=None):
        def logic(store):
            # Robustness: Check if store has keyPath (in-line keys)
            if store.keyPath and key is not None:
                # If keyPath explicitly set, inject key into Python dict BEFORE conversion
                kp = store.keyPath
                if isinstance(kp, str):
                    item[kp] = key
            
            js_val = _to_js_obj(item)

            if store.keyPath:
                 return store.add(js_val)
            else:
                 return store.add(js_val, key) if key else store.add(js_val)
        return await self.db._execute_rw(table_name, logic)

    async def put(self, table_name, item, key=None):
        def logic(store):
            # Robustness: Check if store has keyPath (in-line keys)
            if store.keyPath and key is not None:
                 kp = store.keyPath
                 if isinstance(kp, str):
                     item[kp] = key
            
            js_val = _to_js_obj(item)
            
            if store.keyPath:
                 return store.put(js_val)
            else:
                return store.put(js_val, key) if key else store.put(js_val)
        return await self.db._execute_rw(table_name, logic)
        
    async def get(self, table_name, key):
        def logic(store):
            return store.get(key)
        return await self.db._execute_ro(table_name, logic)

    async def delete(self, table_name, key):
        def logic(store):
            return store.delete(key)
        return await self.db._execute_rw(table_name, logic)
        
    async def clear(self, table_name):
        def logic(store):
            return store.clear()
        return await self.db._execute_rw(table_name, logic)
        
    async def delete_many(self, collection):
         """Optimized bulk delete."""
         # Fallback to fetching keys and deleting one by one for safety if JS optimization is risky
         # Or use collection.each(delete) logic which Table.delete handles.
         # For strict adherence to storage_old.py features, we skip optimized delete_many for now.
         # We'll implement it as loop in Python or simpler.
         # Actually storage_old.py didn't have delete_many.
         # We will implement rudimentary loop here if needed or let Table handle it.
         pass

    async def count(self, collection):
        """Optimized count."""
        # For strict storage_old.py adherence, we just fetch all and count in python (via to_array).
        # But we can optimize if just simple count.
        # Let's delegate to execute_query for now to be safe and consistent with storage_old.py logic (Collection.count implementation).
        pass

    # --- Query Execution ---

    async def execute_query(self, collection: 'Collection'):
        """Executes a query based on the Collection definition."""
        
        conditions = collection._conditions
        order_by = collection._order_by
        reverse = collection._reverse
        limit = collection._limit
        offset = collection._offset
        filter_fn = collection._filter_fn
        
        # Default condition if empty
        if not conditions:
            conditions = [{"index": ":primary", "op": None, "value": None}]

        # Check for Native Cursor Compatibility
        use_native_cursor = False
        target_index = None
        target_range_op = None
        target_range_val = None
        
        if len(conditions) == 1:
            cond = conditions[0]
            cond_index = cond.get("index")
            
            if order_by:
                # Forced order: must match filter index (or filter on primary)
                # Check if order_by IS the primary key
                pk = collection.table.primary_key
                is_pk_sort = (order_by == pk) or (order_by == ":id") or (order_by == ":primary")

                if cond_index in [":primary", ":id", None, pk] or cond_index == order_by:
                     use_native_cursor = True
                     if is_pk_sort:
                         target_index = ":primary"
                     else:
                         target_index = order_by 
                     
                     target_range_op = cond.get("op")
                     target_range_val = cond.get("value")
            else:
                # Natural order
                use_native_cursor = True
                target_index = cond_index
                target_range_op = cond.get("op")
                target_range_val = cond.get("value")

        if use_native_cursor:
            try:
                # Determine if we can use the FAST JS path (No Python Filter)
                if filter_fn is None:
                    results = await self._execute_fast_cursor(
                        collection.table.name, 
                        target_index, 
                        target_range_op, 
                        target_range_val, 
                        reverse, 
                        offset, 
                        limit
                    )
                else:
                    # Use Slow Path (Python Filter) - ported from old logic
                    results = await self._execute_native_cursor_with_filter(
                        collection.table.name,
                        target_index,
                        target_range_op,
                        target_range_val,
                        reverse,
                        offset,
                        limit,
                        filter_fn
                    )
            except Exception as e:
                # If native cursor fails (e.g. Index not found because field is not indexed),
                # fallback to memory execution.
                err_msg = str(e)
                if "NotFoundError" in err_msg or "not found" in err_msg or "index" in err_msg.lower():
                     console.warn(f"QueryEngine: Native cursor failed ({err_msg}). Falling back to memory sort.")
                     use_native_cursor = False 
                     results = await self._execute_memory_fallback(collection)
                else:
                    raise e
        else:
             # Legacy Fallback
             results = await self._execute_memory_fallback(collection)

        # Apply Overlay (Optimistic Updates) implementation
        return self._apply_overlay(results, collection)

    def _apply_overlay(self, results, collection):
         # Logic ported from Indexie._execute_query
         table = collection.table
         overlay = table._overlay # Access internal overlay
         
         if overlay.active and overlay.visible:
             pk = table.primary_key
             order_by = collection._order_by
             reverse = collection._reverse
             
             # Apply Deletes
             deleted_keys = {k for k, v in overlay.mutations.items() if v['type'] == 'delete'}
             if deleted_keys:
                 results = [r for r in results if r.get(pk) not in deleted_keys]

             # Apply Puts
             for key, op in overlay.mutations.items():
                 if op['type'] == 'put':
                      val = op['value']
                      
                      # Merge/Replace
                      # We need to check if it's already in the result set to replace it
                      existing_idx = -1
                      for i, r in enumerate(results):
                           if r.get(pk) == key:
                               existing_idx = i
                               break
                      
                      if existing_idx != -1:
                           results[existing_idx] = val
                      else:
                           # Add to results (optimistic add)
                           results.append(val)
                           
             # Re-sort if we touched things
             if order_by:
                 try:
                     results.sort(key=lambda x: x.get(order_by), reverse=reverse)
                 except: pass

         return results

    async def _execute_fast_cursor(self, store_name, index, op, value, reverse, offset, limit):
        # Setup KeyRange in IDB transaction
        from js import IDBKeyRange
        
        key_range = None
        if op == "equals": key_range = IDBKeyRange.only(value)
        elif op == "above": key_range = IDBKeyRange.lowerBound(value, True)
        elif op == "below": key_range = IDBKeyRange.upperBound(value, True)
        elif op == "starts_with": key_range = IDBKeyRange.bound(value, value + "\uffff")
        
        direction = "prev" if reverse else "next"
        
        def cursor_logic(store):
            # Call the pre-compiled JS function
            return self._fast_cursor_js(store, index, key_range, direction, offset, limit)

        # Execute
        batch_results = await self.db._execute_ro(store_name, cursor_logic)
        
        # Resolve Promise & Convert
        if hasattr(batch_results, 'then'):
            batch_results = await batch_results
        
        if hasattr(batch_results, 'to_py'):
             batch_results = batch_results.to_py()
        
        if not isinstance(batch_results, list):
             try: batch_results = list(batch_results)
             except: pass
             
        return batch_results

    async def _execute_native_cursor_with_filter(self, store_name, index, op, value, reverse, offset, limit, filter_fn):
        # Python Logic for complex filtering
        
        from js import IDBKeyRange
        key_range = None
        if op == "equals": key_range = IDBKeyRange.only(value)
        elif op == "above": key_range = IDBKeyRange.lowerBound(value, True)
        elif op == "below": key_range = IDBKeyRange.upperBound(value, True)
        elif op == "starts_with": 
             val = value
             next_val = val[:-1] + chr(ord(val[-1]) + 1)
             key_range = IDBKeyRange.bound(val, next_val, False, True)
             
        direction = "prev" if reverse else "next"
        
        # Define the cursor processing logic (closure)
        def process_cursor(target, range_val, dir_val, off_val, lim_val, fil_val, resolve, reject):
            results = []
            state = {
                "count": 0,       
                "skipped": 0      
            }
            
            req = target.openCursor(range_val, dir_val)
            
            def on_success(e):
                cursor = e.target.result
                if cursor:
                    # Get Item
                    item = cursor.value
                    
                    # Apply Filter
                    should_include = True
                    # Must convert to Python for the lambda
                    py_item = item.to_py() if hasattr(item, 'to_py') else item
                    
                    if not fil_val(py_item):
                        should_include = False
                    else:
                        item = py_item # Optimization: use converted
                    
                    # Handle Manual Offset (Slow Skip)
                    if should_include and off_val > 0:
                        if state["skipped"] < off_val:
                            state["skipped"] += 1
                            should_include = False
                    
                    if should_include:
                        results.append(item)
                        state["count"] += 1
                        
                        if lim_val is not None and state["count"] >= lim_val:
                            resolve(to_js(results))
                            return

                    cursor.continue_()
                else:
                    resolve(to_js(results))
            
            def on_error(e):
                 reject(e.target.error)

            req.onsuccess = create_proxy(on_success)
            req.onerror = create_proxy(on_error)

        def cursor_logic(store):
            target = store
            if index and index not in [":primary", ":id"]:
                target = store.index(index)
            
            promise = Promise.new(create_proxy(lambda res, rej: process_cursor(
                target, key_range, direction, offset, limit, filter_fn, res, rej
            )))
            return promise

        batch_results = await self.db._execute_ro(store_name, cursor_logic)
        
        if hasattr(batch_results, 'then'):
            batch_results = await batch_results
            
        if hasattr(batch_results, 'to_py'):
             batch_results = batch_results.to_py()
             
        return batch_results

    async def _execute_memory_fallback(self, collection):
        # Legacy: Fetch All -> Sort -> Filter -> Slice in Python
        # Used for complex queries (OR clauses, multi-index sort/filter mismatch)
        
        all_results_dict = {} # PK -> Item
        
        conditions = collection._conditions or [{"index": ":primary", "op": None, "value": None}]
        
        for cond in conditions:
            idx = cond.get("index")
            op = cond.get("op")
            val = cond.get("value")
            
            def fetch_logic(store):
                target = store
                key_range = None
                
                if idx and idx not in [":primary", ":id"]:
                    if store.indexNames.contains(idx):
                        target = store.index(idx)
                        
                from js import IDBKeyRange
                if op == "equals": key_range = IDBKeyRange.only(val)
                elif op == "above": key_range = IDBKeyRange.lowerBound(val, True)
                elif op == "below": key_range = IDBKeyRange.upperBound(val, True)
                elif op == "starts_with": 
                     v = val
                     nv = v[:-1] + chr(ord(v[-1]) + 1)
                     key_range = IDBKeyRange.bound(v, nv, False, True)
                
                if key_range:
                    return target.getAll(key_range)
                else:
                    return target.getAll()

            batch = await self.db._execute_ro(collection.table.name, fetch_logic)
            
            if hasattr(batch, 'to_py'): batch = batch.to_py()
            
            pk = collection.table.primary_key
            for item in batch:
                item_key = None
                if pk:
                    item_key = item.get(pk)
                else:
                    item_key = item.get("id")
                
                if item_key is not None:
                    all_results_dict[item_key] = item
                else:
                    pass

        results = list(all_results_dict.values())
        
        if collection._order_by:
            key = collection._order_by
            try:
                results.sort(key=lambda x: x.get(key), reverse=collection._reverse)
            except:
                pass 
        
        if collection._filter_fn:
            results = [x for x in results if collection._filter_fn(x)]
            
        start = collection._offset
        end = start + collection._limit if collection._limit is not None else None
        
        return results[start:end]
