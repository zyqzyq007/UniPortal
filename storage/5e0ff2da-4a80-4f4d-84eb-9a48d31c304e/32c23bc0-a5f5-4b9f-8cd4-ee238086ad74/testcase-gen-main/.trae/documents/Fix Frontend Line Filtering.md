The user reports that the source code coverage display is still showing the entire file instead of just the target function, even after the backend changes.

I suspect the frontend `visibleLines` computation might be failing if the backend returns string values for `function_start_line` or `function_end_line`, or if there's an off-by-one error or reactivity issue.

I will modify `Frontend/src/views/ResultView.vue` to:
1.  Add logging to debug the values of `function_start_line` and `function_end_line` received from the backend.
2.  Ensure strict type conversion (parseInt) for the line numbers in the `visibleLines` computed property.
3.  Add a fallback: if `function_end_line` is missing or invalid, default to showing only 20 lines from `start_line` instead of the whole file, or try to find the next closing brace (though that's hard in frontend). Better to trust the backend values but ensure they are treated as numbers.

Actually, looking at `ResultView.vue`:
```javascript
172:   const start = result.value.function_start_line || 1
173:   const end = result.value.function_end_line || lines.length
```
If `function_start_line` is 0 or null, it defaults to 1. If `function_end_line` is null, it defaults to `lines.length`.

I will update the frontend to ensure these are parsed as integers, and maybe add a small "Context" buffer (e.g. +/- 2 lines) for better readability, but strictly respecting the cut-off if provided.

The plan:
1.  Modify `Frontend/src/views/ResultView.vue` to force integer conversion for start/end lines in `visibleLines`.
2.  Verify if the backend is actually returning the values by adding a `console.log` (temporarily) or just ensuring the logic is robust.
