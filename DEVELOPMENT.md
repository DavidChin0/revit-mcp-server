# Development Guide: refresh_view + Auditorías de Keynotes

## Problema Resuelto

**Antes:** Agentes modificaban modelo Revit (tags, keynotes, colores) pero David no veía cambios sin refresco manual.

**Ahora:** Tool `refresh_view()` repinta vista automáticamente. David ve cambios en Revit while agentes auditan.

## Architecture: FastMCP + pyRevit Routes

```
┌─────────────────┐
│  MCP Client     │
│  (Claude Code)  │
└────────┬────────┘
         │ stdio
         ▼
┌──────────────────────────────┐
│  MCP Server (main.py)        │  ← D:\GitHub\revit-mcp-server
│  FastMCP + HTTP client       │
└──────────┬───────────────────┘
           │ HTTP :48884
           ▼
┌──────────────────────────────┐
│  pyRevit Routes Server       │  ← %APPDATA%\pyRevit\Extensions\mcp-server-for-revit-python.extension
│  (running inside Revit)      │
│  handlers: revit_mcp/*.py    │
└──────────┬───────────────────┘
           │
           ▼
       Revit API
```

**Key Points:**
- MCP tools/main.py: editar en repo, restart cliente MCP
- pyRevit routes/handlers: editar en repo, **sync + reload** para aplicar

## Workflow: Editar → Sincronizar → Recargar

### 1. Editar código en repo

```bash
cd D:\GitHub\revit-mcp-server
# Edit revit_mcp/*.py or tools/*.py
git status
```

### 2. Sincronizar a pyRevit (sin admin)

```powershell
D:\GitHub\revit-mcp-server\sync_to_pyrevit.ps1
```

Output:
```
Syncing revit_mcp/ and tools/ from repo to Extension...
  From: D:\GitHub\revit-mcp-server
  To:   C:\Users\consu\AppData\Roaming\pyRevit\Extensions\mcp-server-for-revit-python.extension

[1/2] Syncing revit_mcp/...
  ✓ revit_mcp synced
[2/2] Syncing tools/...
  ✓ tools synced
```

**Lo que hace:** copia carpetas revit_mcp/ y tools/ de repo a extensión APPDATA (sobrescribe).

### 3. Recargar pyRevit desde Revit

Usar MCP tool `execute_revit_code`:

```python
from pyrevit.loader import sessionmgr
sessionmgr.reload_pyrevit()
```

**Timing:**
- Request devuelve "Error: " vacío → normal (reload mata requests activos)
- pyRevit recarga: ~60-90 segundos
- Después: rutas disponibles, MCP tools en siguiente sesión cliente

### 4. Verificar cambios

**Endpoints directo (inmediato post-reload):**
```bash
curl -X POST http://localhost:48884/revit_mcp/refresh_view/ -H "Content-Type: application/json" -d '{}'
# Respuesta: {"status":"refreshed","active_view":"Primer Nivel"}
```

**Tools MCP (próxima sesión cliente):**
```python
# En Claude Code / Cursor / etc. (después de reload completo)
refresh_view()  # ← nueva tool disponible
```

## Case Study: refresh_view (2026-07-03)

### Cambios hechos

**File 1: revit_mcp/view_management.py**
- Agregada ruta: `@api.route("/refresh_view/", methods=["POST"])`
- Implementación: `doc.Regenerate() + uidoc.RefreshActiveView() + UpdateAllOpenViews()`
- Retorna: `{"status":"refreshed","active_view":"<vista_activa>"}`

**File 2: tools/view_management_tools.py**
- Agregada tool MCP: `async def refresh_view(ctx) -> str`
- Wrapper alrededor de POST `/refresh_view/`

### Commits

1. `2971124` — "Add refresh_view tool to repaint Revit views without manual UI refresh"
2. `2ebea2a` — "Document development workflow: sync_to_pyrevit + reload cycle"

### Test flow

```
1. Edit revit_mcp/view_management.py + tools/view_management_tools.py
   ↓
2. git commit (local repo)
   ↓
3. sync_to_pyrevit.ps1
   → revit_mcp/view_management.py copia a %APPDATA%\pyRevit\Extensions\
   → tools/view_management_tools.py copia a %APPDATA%\pyRevit\Extensions\
   ↓
4. execute_revit_code: sessionmgr.reload_pyrevit()
   → pyRevit recarga (~90s)
   ↓
5. POST http://localhost:48884/revit_mcp/refresh_view/
   ← {"status":"refreshed","active_view":"Primer Nivel"}
   ↓
6. (next MCP session) → tool refresh_view() usable
```

## Use Case: Auditoría Keynotes EstimaStruct ↔ Revit

**Objetivo:** validar que Type Mark + CSI en modelo Revit coincidan con partidas BD EstimaStruct.

### Flujo automatizado (sin David clickeando)

```python
# Agente Revit MCP
tags = list_tags()  # Extrae keynotes del modelo actual
# tags = [
#   {"element_id": 123, "keynote": "09-30-13.5", "type_mark": "CER-03"},
#   {"element_id": 124, "keynote": "09-91-23.1", "type_mark": "CER-01"},
#   ...
# ]

# Agente EstimaStruct BD
divergencias = auditar_contra_bd(tags)
# divergencias = [
#   {"element_id": 123, "reason": "CSI 09-30-13.5 no existe en BD", "fix": "usar 09-30-13.1"},
#   {"element_id": 124, "reason": "Type Mark mismatch: es CER-01 pero BD espera CER-02"},
#   ...
# ]

# Agente Revit MCP (corrección)
for divergencia in divergencias:
    tag_elements(
        element_ids=[divergencia["element_id"]],
        type_mark=divergencia["fix"]["type_mark"],
        color=divergencia["fix"]["color"],
        keynote=divergencia["fix"]["keynote"]
    )

# AUTO-REPAINT (SIN DAVID REFRESCANDO)
refresh_view()  # ← David VE cambios inmediatamente

# Reporte
print(auditoría_completa())
# output: CSV/JSON con hallazgos + correcciones aplicadas
```

**Antes (blocker):** David debía recargar Revit manualmente para ver cambios.

**Ahora:** `refresh_view()` automatiza repaint → auditoría completa sin intervención.

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| Edit repo, test endpoint, no cambio visible | Olvidó sync_to_pyrevit.ps1. Rutas cargan desde APPDATA, no repo |
| sync_to_pyrevit.ps1 da permiso error | Requiere acceso APPDATA (normal en Windows). Si sigue fallando, run PowerShell as user (no elevado) |
| reload_pyrevit() devuelve "Error: ", routes sigue sin responder | Normal, reload tarda ~90s. Retry endpoint cada 10s con timeout 180s |
| Nuevo tool no aparece en MCP tras reload | Tool MCP visible en **siguiente sesión cliente** (stdio reinicia). Cliente actual no refresca |
| APPDATA folder no existe | pyRevit debe estar instalado en Revit. Instala pyRevit primero |

## Files Changed

- `revit_mcp/view_management.py` — nueva ruta `refresh_view_handler`
- `tools/view_management_tools.py` — nueva tool `refresh_view`
- `sync_to_pyrevit.ps1` — script sin admin para sincronizar
- `README.md` — documentación workflow desarrollo
- Este archivo (`DEVELOPMENT.md`)

## Next Steps

- [ ] Agentes de auditoría de keynotes EstimaStruct using `refresh_view()`
- [ ] TypeMark TagAll workflow (similar arquitectura)
- [ ] Conexiones acero auditoría (usar refresh_view + `tag_elements`)
