import streamlit as st
from jira import JIRA, JIRAError
import os
import sys
from datetime import datetime
from jira_api import create_epic, clone_issue, load_teams, save_teams


st.set_page_config(
    page_title="Onboarding Tool",
    page_icon=None,
    layout="wide",
    initial_sidebar_state="auto",
)

def load_local_css(file_name):
    with open(file_name) as f:
        st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)

# CSS laden
load_local_css("style.css")

# verschiedene TeamAufgaben
team_required = {
    "TDCMB": ["Software: Jira", "Software: Confluence", "Software: Azure DevOps", "Software: Git", "Software: Python"],
    "TDCME": ["Software: Jira", "Software: Confluence", "Software: Azure DevOps", "Excel-Kurs", "Einführung Intranet"],
}

logo_left, spacer, logo_right = st.columns([2, 7, 1])
with logo_left:
    st.image("https://iotusecase.com/wp-content/uploads/2023/08/Rolls-Royce-Power-Systems-AG-Logo.jpg", width=500)
with logo_right:
    st.image("https://upload.wikimedia.org/wikipedia/commons/thumb/2/2a/Logo_RRPS.svg/1200px-Logo_RRPS.svg.png", width=100)

# --- Konfiguration (hier direkt im Skript oder via Umgebungsvariablen) ---
JIRA_URL = os.getenv("JIRA_URL", "https://rrs-ects.atlassian.net")

# Placeholder für Login-UI
login_placeholder = st.empty()

# --- Multi-page login and main app via session_state ---
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False

# LOGIN PAGE
if not st.session_state.logged_in:
    with login_placeholder.container():
        st.title("Jira Login")
        with st.form("login_form"):
            JIRA_EMAIL = st.text_input("Jira E-Mail", key="login_email")
            JIRA_TOKEN = st.text_input("Jira API-Token", type="password", key="login_token")
            PROJECT_KEY = st.text_input("Jira Projekt-Key", key="login_project")
            submitted = st.form_submit_button("Anmelden")

            if submitted:
                if not JIRA_EMAIL or not JIRA_TOKEN or not PROJECT_KEY:
                    st.error("Bitte alle Felder ausfüllen.")
                else:
                    # Test-Verbindung
                    try:
                        jira = JIRA(
                            server=JIRA_URL,
                            basic_auth=(JIRA_EMAIL, JIRA_TOKEN),
                            options={"verify": False}
                        )
                        # Speichern in session_state
                        st.session_state.jira = jira
                        st.session_state.JIRA_EMAIL = JIRA_EMAIL
                        st.session_state.JIRA_TOKEN = JIRA_TOKEN
                        st.session_state.PROJECT_KEY = PROJECT_KEY
                        st.session_state.logged_in = True
                        st.success("Erfolgreich angemeldet!")
                        login_placeholder.empty()  # Login UI entfernen
                    except Exception as e:
                        st.error(f"Login fehlgeschlagen: {e}")
    # Wenn nach Formular-Eingabe noch nicht angemeldet, stoppen
    if not st.session_state.logged_in:
        st.stop()


# GUI-Titel
st.title("Onboarding Tool")
jira = st.session_state.jira
PROJECT_KEY = st.session_state.PROJECT_KEY

# -----------------------------------
# Sidebar: Team-Verwaltung (Admin-Mode)
# -----------------------------------
st.sidebar.header("Team-Verwaltung")
teams = load_teams()
team_names = list(teams.keys())

admin_mode = st.sidebar.checkbox("Team-Administration aktivieren")
if admin_mode:
    sel = st.sidebar.selectbox(
        "Team wählen oder Neu anlegen",
        ["<Neues Team>"] + team_names,
        key="admin_select"
    )

    # ─── Neuen Team anlegen ─────────────────────────────
    if sel == "<Neues Team>":
        new_name = st.sidebar.text_input("Neuer Teamname", key="new_team")
        new_tasks = st.sidebar.text_area("Pflichtaufgaben (eine pro Zeile)", key="new_tasks")
        if st.sidebar.button("Team anlegen"):
            if not new_name:
                st.sidebar.error("Bitte gib einen Teamnamen ein.")
            elif new_name in teams:
                st.sidebar.error("Dieses Team existiert bereits.")
            else:
                teams[new_name] = [t.strip() for t in new_tasks.splitlines() if t.strip()]
                save_teams(teams)
                st.sidebar.success(f"Team '{new_name}' angelegt - bitte Seite neu laden.")
                st.stop()

    # ─── Bestehendes Team bearbeiten oder löschen ────────
    else:
        # Bearbeiten
        edited = st.sidebar.text_area(
            f"Pflichtaufgaben für '{sel}' (eine pro Zeile)",
            value="\n".join(teams[sel]),
            key="edit_tasks"
        )
        if st.sidebar.button("Änderungen speichern"):
            teams[sel] = [t.strip() for t in edited.splitlines() if t.strip()]
            save_teams(teams)
            st.sidebar.success(f"Team '{sel}' aktualisiert - bitte Seite neu laden.")
            st.stop()

        # Löschen
        st.sidebar.markdown("---")
        if st.sidebar.button(f"Team '{sel}' löschen", key="delete_team"):
            teams.pop(sel, None)
            save_teams(teams)
            st.sidebar.success(f"Team '{sel}' gelöscht - bitte Seite neu laden.")
            st.stop()


# Auswahl des Epics
st.subheader("Wähle ein Epic zum Klonen")
try:
    jql_epics = f'project = "{PROJECT_KEY}" AND issuetype = Epic ORDER BY created DESC'
    epic_issues = jira.search_issues(jql_epics, maxResults=50)
    epic_labels = [f"{ep.key} - {ep.fields.summary}" for ep in epic_issues]
except JIRAError as e:
    st.error(f"Projekt-Key ungültig oder keine Rechte: {e.text}")
    st.stop()

selected = st.selectbox("Available Epics:", ["-- Bitte wählen --"] + epic_labels, key="select_epic")
if not selected or selected.startswith("--"):
    st.warning("Bitte wähle ein Epic aus.")
    st.stop()

template_key = selected.split(" - ")[0]

# Lade Team-Pflichtaufgaben:
team_required = load_teams()

# --------------------------------
# Team-Auswahl (wie vorher, nur Quelle geändert)
team = st.selectbox("Team auswählen", ["-- wählen --"] + list(team_required.keys()))
if team.startswith("--"):
    st.stop()

preselected_tasks = team_required.get(team, [])

# Eingabefelder
employee = st.text_input("Name des Mitarbeiters", key="emp_input")
start_date = st.date_input("Startdatum", key="start_date")
end_date = st.date_input("Enddatum der Einarbeitung", key="end_date")
emp_type = st.selectbox("Mitarbeiter-Typ", ["Intern", "Extern"], key="type_sel")
teamlead_name = st.text_input("Name des Teamleiters", key="tl_name")
mentor_name = st.text_input("Name des Paten", key="mentor_name")

# Datumsvalidierung
if employee and end_date < start_date:
    st.error("Das Enddatum darf nicht vor dem Startdatum liegen.")

# Aufgabenvorschau laden
tasks, task_labels = [], []
if template_key:
    try:
        subtasks = jira.search_issues(f'"Epic Link" = {template_key}')
        tasks = subtasks
        task_labels = [t.fields.summary for t in subtasks]
    except Exception as e:
        st.error(f"Fehler beim Laden der Aufgaben: {e}")

# Auswahl der Aufgaben
valid_defaults = [t for t in preselected_tasks if t in task_labels]
selected_labels = st.multiselect(
    "Aufgaben auswählen zum Klonen",
    task_labels,
    default=valid_defaults,
    key="task_select"
)
selected_tasks = [tasks[task_labels.index(lbl)] for lbl in selected_labels]

# Zuweisung pro Aufgabe
assignment = {}
for i, lbl in enumerate(selected_labels):
    choice = st.selectbox(
        f"Zuständigkeit für '{lbl}'", ["Teamleiter", "Pate", "Mitarbeiter"], key=f"assign_{i}"
    )
    if choice == "Mitarbeiter":
        emp_name = st.text_input(f"Wer ist zuständig für '{lbl}'? (Name) ", key=f"resp_{i}")
        assignment[lbl] = (choice, emp_name)
    else:
        assignment[lbl] = (choice, None)




# Reset-Button für alle Felder
if st.button("Zurücksetzen", key="reset_button"):
    for k in ["emp_input", "start_date", "end_date", "type_sel", "tl_name", "mentor_name", "task_select", "resp_name"] + [f"assign_{i}" for i in range(len(selected_labels))]:
        st.session_state.pop(k, None)
    # Seite neu laden, falls möglich
    st.info("Bitte lade die Seite neu, um alle Eingaben zurückzusetzen.")

# Button zum Starten
if st.button("Onboarding starten", key="start_button"):
    # Validierung
    if not employee:
        st.warning("Bitte gib den Namen des Mitarbeiters ein.")
    elif not template_key:
        st.warning("Bitte wähle einen Mitarbeitertyp aus.")
    elif not teamlead_name or not mentor_name:
        st.warning("Bitte gib Name von Teamleiter und Paten ein.")
    else:
        start_str = start_date.isoformat()
        end_str = end_date.isoformat()

    # IDs der Teamleiter, Mentoren und Mitarbeiter suchen
    try:
        tl_id = jira.search_users(query=teamlead_name.strip())[0].accountId
    except Exception:
        st.error(f"Teamleiter '{teamlead_name}' nicht gefunden.")
        st.stop()
    try:
        mentor_id = jira.search_users(query=mentor_name.strip())[0].accountId
    except Exception:
        st.error(f"Pate '{mentor_name}' nicht gefunden.")
        st.stop()
    try:
        emp_id = jira.search_users(query=employee.strip())[0].accountId
    except Exception:
        st.error(f"Mitarbeiter '{employee}' nicht gefunden.")
        st.stop()

    # Epic erstellen
    try:
        new_epic = create_epic(
            jira, PROJECT_KEY, template_key,
            employee, start_str, end_str
        )
        st.success(f"Epic erstellt: {new_epic.key}")
    except Exception as e:
        st.error(f"Fehler beim Erstellen des Epics: {e}")
        st.stop()



    # Klonen der Aufgaben mit individueller Zuweisung
    if selected_tasks:
        count = 0
        for task in selected_tasks:
            lbl = task.fields.summary
             
            choice, person = assignment[lbl]
            if choice == "Teamleiter":
                accountId = tl_id
            elif choice == "Pate":
                accountId = mentor_id
            else:
                accountId = emp_id
            try:
                new_issue = clone_issue(
                jira,
                src_key=task.key,
                project_key=PROJECT_KEY,
                parent_epic=new_epic.key,
                assignee_id=accountId,
                start_iso=start_str,
                due_iso=end_str)

                count += 1
            except Exception as e:
                st.error(f"Fehler beim Klonen von '{lbl}': {e}")
        st.success(f"{count} Aufgaben geklont und zugewiesen.")

