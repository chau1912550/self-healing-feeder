# Factory IO scenes

**Tool:** Factory IO

**What goes here:** A virtual control panel (stack lights per switch, reset and tie buttons, a lockout lamp) driven by the study over Modbus TCP, and the Modbus address map shared with any real board later.

**How:** The Modbus TCP driver needs the Modbus & OPC or Ultimate edition of Factory IO. Save scenes (`.factoryio`) and the address map here.

After exporting, register the export so the health check can tell when it goes stale:

```bash
.venv\Scripts\python scripts\register_export.py <id>
```

See [`../workflow.toml`](../workflow.toml) for the rules. Everything here supports a simulation study; none of it is field equipment or field data.
