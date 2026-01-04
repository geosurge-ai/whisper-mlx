"""
Python code execution tool.

Executes Python code in an isolated subprocess with timeout protection.
Supports data analysis libraries and visualization output.
"""

import base64
import json
import multiprocessing
import os
import tempfile

from ..base import tool
from .data_store import get_session_context, get_session_assets_dir


def _execute_python_code(code: str, output_dir: str, result_queue) -> None:
    """Execute Python code in a subprocess."""
    import io
    import sys
    import traceback
    
    old_stdout = sys.stdout
    old_stderr = sys.stderr
    captured_stdout = io.StringIO()
    captured_stderr = io.StringIO()
    
    result = {
        "success": False,
        "stdout": "",
        "stderr": "",
        "error": None,
        "return_value": None,
    }
    
    try:
        sys.stdout = captured_stdout
        sys.stderr = captured_stderr
        
        exec_globals = {
            "__builtins__": __builtins__,
            "__name__": "__main__",
            "OUTPUT_DIR": output_dir,
        }
        
        try:
            import matplotlib
            matplotlib.use('Agg')
            import matplotlib.pyplot as plt
            plt.rcParams['savefig.directory'] = output_dir
        except ImportError:
            pass
        
        exec(code, exec_globals)
        result["success"] = True
        
    except Exception as e:
        result["error"] = f"{type(e).__name__}: {str(e)}"
        result["stderr"] = traceback.format_exc()
    finally:
        sys.stdout = old_stdout
        sys.stderr = old_stderr
        result["stdout"] = captured_stdout.getvalue()
        result["stderr"] = captured_stderr.getvalue() or result.get("stderr", "")
    
    result_queue.put(result)


@tool(
    name="run_python",
    description="Execute Python code and return output. Full Python environment with pandas, numpy, scipy, matplotlib, seaborn, plotly available. Use for data analysis, calculations, statistics, or generating visualizations. Use print() for output. For charts, save to OUTPUT_DIR: plt.savefig(f'{OUTPUT_DIR}/chart.png'). Generated images are returned as embedded base64.",
    parameters={
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": "Python code to execute. Use print() for output. For visualizations, save to OUTPUT_DIR variable (e.g., plt.savefig(f'{OUTPUT_DIR}/chart.png')).",
            },
            "timeout": {
                "type": "integer",
                "description": "Max execution time in seconds (default 30)",
            },
        },
        "required": ["code"],
    },
)
def run_python(code: str, timeout: int = 30) -> str:
    """Execute Python code and return the output."""
    session_id = get_session_context()
    using_session_dir = session_id is not None
    
    if using_session_dir:
        output_dir = str(get_session_assets_dir(session_id))
        temp_dir_context = None
    else:
        temp_dir_context = tempfile.TemporaryDirectory(prefix="run_python_")
        output_dir = temp_dir_context.name
    
    try:
        try:
            ctx = multiprocessing.get_context('fork')
        except ValueError:
            ctx = multiprocessing.get_context()
        
        result_queue = ctx.Queue()
        process = ctx.Process(
            target=_execute_python_code,
            args=(code, output_dir, result_queue)
        )
        process.start()
        process.join(timeout=timeout)
        
        if process.is_alive():
            process.terminate()
            process.join(timeout=1)
            return json.dumps({
                "success": False,
                "stdout": "",
                "stderr": "",
                "error": f"Code execution exceeded {timeout} seconds (timeout)",
                "return_value": None,
                "images": [],
            })
        
        try:
            result = result_queue.get_nowait()
        except Exception:
            result = {
                "success": False,
                "stdout": "",
                "stderr": "",
                "error": "Failed to get result from subprocess",
                "return_value": None,
            }
        
        # Scan for generated images
        images = []
        image_extensions = {'.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp'}
        
        for filename in os.listdir(output_dir):
            filepath = os.path.join(output_dir, filename)
            if os.path.isfile(filepath):
                ext = os.path.splitext(filename)[1].lower()
                if ext in image_extensions:
                    with open(filepath, 'rb') as f:
                        data = f.read()
                    
                    mime_types = {
                        '.png': 'image/png',
                        '.jpg': 'image/jpeg',
                        '.jpeg': 'image/jpeg',
                        '.gif': 'image/gif',
                        '.svg': 'image/svg+xml',
                        '.webp': 'image/webp',
                    }
                    mime_type = mime_types.get(ext, 'application/octet-stream')
                    b64_data = base64.b64encode(data).decode('utf-8')
                    data_uri = f"data:{mime_type};base64,{b64_data}"
                    
                    images.append({
                        "filename": filename,
                        "data": data_uri,
                        "persisted": using_session_dir,
                    })
        
        result["images"] = images
        if using_session_dir and session_id:
            result["assets_dir"] = f"sessions/{session_id}/assets"
        
    finally:
        if temp_dir_context is not None:
            temp_dir_context.cleanup()
    
    return json.dumps(result)


TOOL = run_python
