import asyncio

async def execute_command(command, timeout=300, cwd=None):
    """
    Executes a shell command asynchronously with timeout and returns the output.
    Default timeout: 300 seconds (5 minutes)
    """
    try:
        process = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )
        
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            # Kill the process if it times out
            try:
                process.kill()
                await process.wait()
            except:
                pass
            return f"Command timed out after {timeout} seconds. Consider using faster alternatives or limiting scope (e.g., amass -timeout 2, nmap -T4 --max-retries 1)."
        
        output = stdout.decode().strip()
        error = stderr.decode().strip()

        if output and error:
            return f"{output}\n[stderr]\n{error}"
        if output:
            return output
        if error:
            return f"[stderr]\n{error}"
        return "Command executed successfully (no output)."
    except Exception as e:
        return f"Failed to execute command: {str(e)}"
