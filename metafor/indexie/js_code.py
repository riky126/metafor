
# Optimized Pure JS Cursor Logic
# This runs entirely in the browser thread, avoiding Python overhead for simple queries.
JS_FAST_CURSOR_CODE = """
(store, indexName, range, direction, offset, limit) => {
    return new Promise((resolve, reject) => {
        let req;
        try {
            let target = store;
            if (indexName && indexName !== ":primary" && indexName !== ":id") {
                target = store.index(indexName);
            }
            req = target.openCursor(range, direction);
        } catch (e) {
            reject(e);
            return;
        }

        let count = 0;
        let advanced = false;
        let results = [];
        
        req.onsuccess = (e) => {
            let cursor = e.target.result;
            if (!cursor) {
                resolve(results);
                return;
            }
            
            // Native skip using advance()
            if (offset > 0 && !advanced) {
                advanced = true;
                cursor.advance(offset);
                return;
            }
            
            results.push(cursor.value);
            count++;
            
            if (limit !== null && limit !== undefined && count >= limit) {
                resolve(results);
                return;
            }
            
            cursor.continue();
        };
        
        req.onerror = (e) => reject(e.target.error);
    });
}
"""
