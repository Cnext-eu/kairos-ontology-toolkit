---
name: SC-document
description: >
  Search, read, create, and update documents in an Outline wiki.
  Use when the user wants to manage documentation stored in the
  configured Outline workspace.
---

# SC — Document (Outline Wiki)

You help the user manage documentation in an **Outline wiki** instance.
This skill supports full CRUD operations: search, read, create, and update.

## Configuration

Environment variables are read from the `.env` file in the repository root:

| Variable | Required | Description |
|----------|----------|-------------|
| `OUTLINE_API_KEY` | Yes | Bearer token for API authentication |
| `OUTLINE_API_URL` | Yes | Base API URL (e.g., `https://myteam.getoutline.com/api`) |
| `OUTLINE_COLLECTION_ID` | No | Default collection to scope operations |

### Reading configuration

Before making any API call, read the configuration:

```powershell
$envFile = Get-Content ".env" -ErrorAction Stop
$apiKey = ($envFile | Where-Object { $_ -match "^OUTLINE_API_KEY=" }) -replace "^OUTLINE_API_KEY=", ""
$apiUrl = ($envFile | Where-Object { $_ -match "^OUTLINE_API_URL=" }) -replace "^OUTLINE_API_URL=", ""
$collectionId = ($envFile | Where-Object { $_ -match "^OUTLINE_COLLECTION_ID=" }) -replace "^OUTLINE_COLLECTION_ID=", ""
```

Validate that `OUTLINE_API_KEY` and `OUTLINE_API_URL` are set. If missing, tell
the user to add them to `.env`.

## Authentication

All requests use Bearer token auth:

```
Authorization: Bearer <OUTLINE_API_KEY>
Content-Type: application/json
```

Helper for headers:

```powershell
$headers = @{
    Authorization  = "Bearer $apiKey"
    "Content-Type" = "application/json"
}
```

## Available Operations

### 1. Search documents

```powershell
$body = @{ query = "<search term>" } | ConvertTo-Json
$response = Invoke-RestMethod -Uri "$apiUrl/documents.search" `
  -Method POST -Headers $headers -Body $body
$response.data | ForEach-Object { "$($_.document.title) — $($_.document.id)" }
```

Optional body parameters:
- `collectionId` — limit to a specific collection
- `limit` — max results (default 25)
- `offset` — pagination offset
- `dateFilter` — `"day"`, `"week"`, `"month"`, `"year"`
- `includeArchived` — boolean

### 2. Read a document by ID

```powershell
$body = @{ id = "<document-id>" } | ConvertTo-Json
$response = Invoke-RestMethod -Uri "$apiUrl/documents.info" `
  -Method POST -Headers $headers -Body $body
$response.data.text  # Markdown content
```

### 3. Create a document

```powershell
$body = @{
    title        = "<document title>"
    text         = "<markdown content>"
    collectionId = $collectionId  # or a specific collection ID
    publish      = $true          # set $false to create as draft
} | ConvertTo-Json -Depth 10
$response = Invoke-RestMethod -Uri "$apiUrl/documents.create" `
  -Method POST -Headers $headers -Body $body
Write-Output "Created: $($response.data.title) — $($response.data.id)"
```

Optional parameters:
- `parentDocumentId` — create as a child of another document
- `templateId` — use an existing document as template
- `template` — boolean, mark this document as a template

### 4. Update a document

```powershell
$body = @{
    id    = "<document-id>"
    title = "<new title>"       # optional
    text  = "<new content>"     # optional — full replacement
} | ConvertTo-Json -Depth 10
$response = Invoke-RestMethod -Uri "$apiUrl/documents.update" `
  -Method POST -Headers $headers -Body $body
Write-Output "Updated: $($response.data.title)"
```

Optional parameters:
- `append` — boolean, if `$true` appends `text` instead of replacing
- `publish` — boolean, publish a draft
- `done` — boolean, mark task as done

### 5. List collections

```powershell
$body = @{} | ConvertTo-Json
$response = Invoke-RestMethod -Uri "$apiUrl/collections.list" `
  -Method POST -Headers $headers -Body $body
$response.data | ForEach-Object { "$($_.name) — $($_.id)" }
```

### 6. List documents in a collection

```powershell
$body = @{ collectionId = "<collection-id>" } | ConvertTo-Json
$response = Invoke-RestMethod -Uri "$apiUrl/documents.list" `
  -Method POST -Headers $headers -Body $body
$response.data | ForEach-Object { "$($_.title) — $($_.id)" }
```

### 7. Delete a document (archive)

```powershell
$body = @{ id = "<document-id>" } | ConvertTo-Json
$response = Invoke-RestMethod -Uri "$apiUrl/documents.delete" `
  -Method POST -Headers $headers -Body $body
Write-Output "Archived document."
```

> Outline soft-deletes by default (moves to archive). Use `permanent = $true`
> in the body for permanent deletion — ask for user confirmation first.

## Workflow

1. **Parse the user's request** — determine the operation (search, read, create, update, list).
2. **Read configuration** from `.env`.
3. **Validate** — ensure required variables are present.
4. **Execute the API call** using `Invoke-RestMethod`.
5. **Present results** — show titles, content, or confirmation as appropriate.
6. **Offer follow-up** — suggest related actions (e.g., after creating, offer to add sub-pages).

### Creating documentation from code

When the user asks to "document" something (a module, a decision, a process):

1. Generate the Markdown content based on the codebase/context.
2. Ask which collection to place it in (or use `OUTLINE_COLLECTION_ID` default).
3. Create the document via the API.
4. Return the document URL: `<OUTLINE_API_URL without /api>/doc/<slug>-<id>`

### Updating existing documentation

When the user asks to update a document:

1. Search or fetch the document by title/ID.
2. Show current content to the user.
3. Make the requested changes to the Markdown.
4. Update via the API (full replace or append based on context).

## Error Handling

| HTTP Status | Meaning | Action |
|-------------|---------|--------|
| 401 | Unauthorized | API key expired or invalid. Ask user to regenerate at Outline settings → API. |
| 403 | Forbidden | User doesn't have permission for this collection/document. |
| 404 | Not Found | Document or collection deleted/archived. |
| 429 | Rate Limited | Wait and retry. Outline rate limits to ~120 req/min. |

| Situation | Action |
|-----------|--------|
| `.env` missing | Tell user to create `.env` with required `OUTLINE_*` variables |
| `OUTLINE_API_URL` missing | Ask user for their Outline instance URL |
| No search results | Suggest broadening query or listing collections first |
| Collection not found | List available collections and ask user to pick one |

## Tips

- The Outline API uses **POST for all endpoints** (including reads).
- Document content is Markdown in the `text` field.
- Search results include a `ranking` score and `context` snippet.
- Use `collectionId` to narrow search scope when the workspace is large.
- Document URLs follow the pattern: `https://<instance>/doc/<slug>-<id>`
- For large documents, summarize key sections rather than dumping everything.
