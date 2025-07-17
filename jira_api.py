from jira import JIRA
import requests
from io import BytesIO
from atlassian import Confluence
import os, tempfile, shutil, json
from jira.exceptions import JIRAError

SC_PROPERTY = "com.railsware.SmartChecklist.checklist"
CHECKLIST_CF = "customfield_10619"

def copy_attachments(jira, src, dst):
    """
    Lädt alle Anhänge des Quell-Issues herunter und hängt sie an den Ziel-Issue an.
    Jira Cloud verlangt dafür den Header  X-Atlassian-Token: no-check.
    """
    atts = getattr(src.fields, "attachment", None)
    if not atts:                # kein Attachment-Feld oder leer
        return

    for att in atts:
        download_url = att.content        # enthält bereits ein einmaliges JWT-Token
        # 1) Datei herunterladen – unbedingt Header setzen!
        with jira._session.get(
                download_url,
                headers={'X-Atlassian-Token': 'no-check'},
                stream=True,
                allow_redirects=True) as resp:
            resp.raise_for_status()

            # 2) In eine Temp-Datei schreiben (chunk-weise, falls >10 MB)
            with tempfile.NamedTemporaryFile(delete=False) as tmpf:
                for chunk in resp.iter_content(chunk_size=8192):
                    if chunk:            # Filter für Keep-Alive-Chunks
                        tmpf.write(chunk)
                tmp_path = tmpf.name

        # 3) Wieder an den neuen Issue anhängen
        jira.add_attachment(issue=dst, attachment=tmp_path, filename=att.filename)
        os.unlink(tmp_path)              # Tempdatei löschen


def copy_comments(jira, src, dst):
    """Kommentare inkl. Autor & Timestamp kopieren."""
    for c in jira.comments(src):
        header = f"_Cloned from {src.key} – {c.author.displayName} {c.created}_\n\n"
        jira.add_comment(dst, header + c.body)

def copy_checklist(jira, src_key: str, dst_key: str) -> None:
    """Überträgt die Smart-Checklist als Markdown-String ins Ziel-Issue."""
    # Roh-Markdown aus dem Customfield holen
    src_issue = jira.issue(src_key, fields=CHECKLIST_CF)
    md = src_issue.raw["fields"].get(CHECKLIST_CF)
    if not md:
        return   # nichts zu kopieren

    # Property-URL bilden
    url = (f"{jira._options['server'].rstrip('/')}"
           f"/rest/api/3/issue/{dst_key}/properties/{SC_PROPERTY}")

    # ► WICHTIG: Plain-String als JSON-String speichern (kein Objekt!)
    jira._session.put(
        url,
        data=json.dumps(md),               
        headers={"Content-Type": "application/json"}
    )

def copy_weblinks(jira, src_key: str, dst_key: str) -> None:
    """
    Überträgt alle 'Web Link'-Remote-Links vom Quell- in den Ziel-Vorgang.
    Doppelte Links werden übersprungen (Jira gibt dann HTTP 409 zurück).
    """
    try:
        # Alle Remote-Links des Quell-Issues holen
        for rlink in jira.remote_links(src_key):
            obj = rlink.object          # enthält url, title, icon, status …
            payload = {
                "url":   obj.url,
                "title": obj.title or obj.url
            }
            try:
                jira.add_remote_link(dst_key, payload)
            except JIRAError as e:      # 409 = bereits vorhanden
                if e.status_code != 409:
                    raise
    except JIRAError as e:
        # Keine Links oder Rechte fehlen → einfach überspringen
        print(f"Warnung: Web-Links von {src_key} konnten nicht gelesen werden ({e}).")

def copy_confluence_links(jira, src_key: str, dst_key: str) -> None:
    """
    Kopiert alle Confluence-Remote-Links (UI-Box „Confluence-Inhalt“)
    aus src_key nach dst_key. Erkennung und Anlegen basieren ausschließlich
    auf rl.raw, um fehlende Attribute zu vermeiden.
    """
    try:
        for rl in jira.remote_links(src_key):
            data = rl.raw                        # Vollständiges JSON des Links

            # ── Confluence erkennen ───────────────────────────────
            rel   = (data.get("relationship") or "").lower()
            app   = data.get("application") or {}
            app_t = app.get("type", "")
            icon  = (data.get("object") or {}).get("icon", {})
            icon_t= (icon.get("title") or "").lower()

            if not (
                rel.startswith("confluence") or
                app_t == "com.atlassian.confluence" or
                icon_t.startswith("confluence")
            ):
                continue
            # ──────────────────────────────────────────────────────

            # Ziel-Payload aus bestehendem JSON nachbauen
            payload_object = {
                "url":   data["object"]["url"],
                "title": data["object"].get("title", data["object"]["url"]),
                "icon":  icon
            }
            application = {
                "type": "com.atlassian.confluence",
                "name": "Confluence"
            }

            try:
                jira.add_remote_link(
                    dst_key,
                    payload_object,
                    globalId=data.get("globalId"),
                    application=application,
                    relationship="confluence content"
                )
            except JIRAError as e:
                if e.status_code != 409:   # 409 = Link existiert schon
                    raise
    except JIRAError as e:
        print(f"Warnung: Confluence-Links von {src_key} wurden nicht kopiert ({e}).")


def create_epic(jira_client, project_key, template_key, employee_name, start_date, end_date):

    template = jira_client.issue(template_key)

    summary = f"{template.fields.summary} - {employee_name}"

    fields = {
        "project": {"key": project_key},
        "summary": summary,
        "description": template.fields.description,
        "issuetype": {"name": "Epic"},
        "assignee": {"accountId": jira_client.current_user()},
        "customfield_10015": start_date,
        "duedate": end_date
    }
    return jira_client.create_issue(fields=fields)



def clone_issue(jira, src_key: str,
                project_key: str,
                parent_epic: str,
                assignee_id: str,
                start_iso: str,
                due_iso: str) -> str:
    """Klon eines Tasks – gibt den neuen Issue-Key zurück."""
    # Quell-Issue inklusive gewünschter Felder laden
    src = jira.issue(
    src_key,
    fields=f"summary,description,issuetype,{CHECKLIST_CF},attachment,comment",
    expand="attachment"
    )

    # 1) neues Issue anlegen (Smart Checklist _nicht_ mitschicken → Property ist robuster)
    new_issue = jira.create_issue(fields={
        "project":     {"key": project_key},
        "summary":     src.fields.summary,
        "description": src.fields.description,
        "issuetype":   {"id": src.fields.issuetype.id},
        "parent":      {"key": parent_epic},
        "assignee":    {"accountId": assignee_id},
        "customfield_10015": start_iso,
        "duedate":            due_iso
    })

    # 2) Kommentare, Attachments, Smart Checklist übertragen
    try:
        copy_comments(jira, src, new_issue)
        copy_attachments(jira, src, new_issue)
        copy_checklist(jira, src_key, new_issue.key)
        copy_weblinks(jira, src_key, new_issue.key)
        copy_confluence_links(jira, src_key, new_issue.key)

    except JIRAError as e:
        # hier nur loggen – das neue Issue existiert ja bereits
        print(f"Warnung bei Clone {src_key}: {e}")

    # 3) (optional) Status auf „To Do“ setzen
    try:
        jira.transition_issue(new_issue, "To Do")
    except JIRAError:
        pass

    return new_issue.key


