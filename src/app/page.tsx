"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { signIn, signOut, useSession } from "next-auth/react";
import styles from "./page.module.css";

const BACKEND_BASE_URL = process.env.NEXT_PUBLIC_BACKEND_BASE_URL || "http://127.0.0.1:8000";
const GOOGLE_SHEETS_URL_RE = /https?:\/\/docs\.google\.com\/spreadsheets\/d\/([a-zA-Z0-9-_]+)/;

type Project = {
  id: string;
  name: string;
  user_id: string;
};

type Message = {
  role: "system" | "user" | "assistant";
  content: string;
};

const makeId = () => {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `local-${Math.random().toString(36).slice(2)}`;
};

export default function Home() {
  const { data: session, status } = useSession();
  const [projects, setProjects] = useState<Project[]>([]);
  const [activeProject, setActiveProject] = useState<Project | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [prompt, setPrompt] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loadingMessages, setLoadingMessages] = useState(false);
  const [streaming, setStreaming] = useState(false);
  const [projectModalOpen, setProjectModalOpen] = useState(false);
  const [projectModalMode, setProjectModalMode] = useState<"create" | "rename">("create");
  const [projectDraftName, setProjectDraftName] = useState("");
  const [projectMenuOpenId, setProjectMenuOpenId] = useState<string | null>(null);
  const [editingProjectId, setEditingProjectId] = useState<string | null>(null);
  const [accountMenuOpen, setAccountMenuOpen] = useState(false);
  const chatEndRef = useRef<HTMLDivElement | null>(null);
  const accountMenuRef = useRef<HTMLDivElement | null>(null);
  const projectMenuRef = useRef<HTMLDivElement | null>(null);

  const token = session?.id_token;
  const googleAccessToken = session?.access_token;

  const userId = useMemo(() => {
    return session?.user?.email ?? "";
  }, [session]);
  const displayName = session?.user?.name?.trim() || session?.user?.email || "Usuario";
  const displayEmail = session?.user?.email || "";
  const displayInitials = useMemo(() => {
    const source = displayName.trim();
    if (!source) return "U";
    const parts = source.split(/\s+/).filter(Boolean);
    if (parts.length === 1) return parts[0][0]?.toUpperCase() || "U";
    return `${parts[0][0] ?? ""}${parts[1][0] ?? ""}`.toUpperCase();
  }, [displayName]);
  const accountMenuItems = useMemo(
    () => [
      {
        id: "logout",
        label: "Log out",
        onClick: () => signOut(),
      },
    ],
    []
  );

  const readErrorDetail = async (res: Response) => {
    try {
      const data = await res.json();
      return data?.detail || data?.message || `Error ${res.status}`;
    } catch {
      return `Error ${res.status}`;
    }
  };

  const handleAuthError = async (res: Response) => {
    if (res.status === 401) {
      setError("Sesión expirada. Volvé a iniciar sesión.");
      await signOut({ redirect: false });
      return true;
    }
    return false;
  };

  const loadProjects = async () => {
    if (!token) return;
    setError(null);
    try {
      const res = await fetch(`${BACKEND_BASE_URL}/projects`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) {
        if (await handleAuthError(res)) return;
        const detail = await readErrorDetail(res);
        throw new Error(detail);
      }
      const data: Project[] = await res.json();
      setProjects(data);
      if (data.length && !activeProject) {
        setActiveProject(data[0]);
      }
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const loadMessages = async (project: Project) => {
    if (!token) return;
    setError(null);
    setLoadingMessages(true);
    try {
      const res = await fetch(`${BACKEND_BASE_URL}/projects/${project.id}/messages`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) {
        if (await handleAuthError(res)) return;
        const detail = await readErrorDetail(res);
        throw new Error(detail);
      }
      const data: Message[] = await res.json();
      setMessages(data);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoadingMessages(false);
    }
  };

  const createProject = async (name: string) => {
    if (!name.trim() || !token) return;
    setError(null);
    try {
      const res = await fetch(`${BACKEND_BASE_URL}/projects`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ name: name.trim() }),
      });
      if (!res.ok) {
        if (await handleAuthError(res)) return;
        const detail = await readErrorDetail(res);
        throw new Error(detail);
      }
      const project: Project = await res.json();
      setProjects((prev) => [project, ...prev]);
      setActiveProject(project);
      setMessages([]);
      setProjectDraftName("");
      setProjectModalOpen(false);
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const renameProject = async (projectId: string, name: string) => {
    if (!name.trim() || !token) return;
    setError(null);
    try {
      const res = await fetch(`${BACKEND_BASE_URL}/projects/${projectId}`, {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ name: name.trim() }),
      });
      if (!res.ok) {
        if (await handleAuthError(res)) return;
        const detail = await readErrorDetail(res);
        throw new Error(detail);
      }
      const updated: Project = await res.json();
      setProjects((prev) => prev.map((p) => (p.id === updated.id ? updated : p)));
      setActiveProject((prev) => (prev && prev.id === updated.id ? updated : prev));
      setProjectDraftName("");
      setEditingProjectId(null);
      setProjectModalOpen(false);
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const deleteProject = async (projectId: string) => {
    if (!token) return;
    setError(null);
    try {
      const wasActive = activeProject?.id === projectId;
      const res = await fetch(`${BACKEND_BASE_URL}/projects/${projectId}`, {
        method: "DELETE",
        headers: {
          Authorization: `Bearer ${token}`,
        },
      });
      if (!res.ok) {
        if (await handleAuthError(res)) return;
        const detail = await readErrorDetail(res);
        throw new Error(detail);
      }
      setProjects((prev) => {
        const remaining = prev.filter((p) => p.id !== projectId);
        setActiveProject((current) => {
          if (!current || current.id !== projectId) return current;
          return remaining.length ? remaining[0] : null;
        });
        return remaining;
      });
      if (wasActive) {
        setMessages([]);
      }
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const buildSheetPreview = async (sheetUrl: string): Promise<string> => {
    if (!googleAccessToken) {
      return "No hay token de acceso de Google disponible. Cerrá sesión y volvé a iniciar para otorgar permisos de Sheets.";
    }

    const match = sheetUrl.match(GOOGLE_SHEETS_URL_RE);
    if (!match) {
      return "No se pudo extraer el ID de la Google Sheet desde la URL.";
    }
    const spreadsheetId = match[1];

    const metaRes = await fetch(
      `https://sheets.googleapis.com/v4/spreadsheets/${spreadsheetId}?fields=properties.title,sheets.properties.title`,
      {
        headers: { Authorization: `Bearer ${googleAccessToken}` },
      }
    );
    if (!metaRes.ok) {
      const detail = await readErrorDetail(metaRes);
      return `No se pudo leer metadata de la Sheet: ${detail}`;
    }

    const meta = await metaRes.json();
    const spreadsheetTitle = meta?.properties?.title || "Sin titulo";
    const firstSheetName = meta?.sheets?.[0]?.properties?.title;
    if (!firstSheetName) {
      return "La Sheet no contiene hojas visibles.";
    }

    const range = `'${String(firstSheetName).replace(/'/g, "''")}'!A1:H12`;
    const valuesRes = await fetch(
      `https://sheets.googleapis.com/v4/spreadsheets/${spreadsheetId}/values/${encodeURIComponent(range)}?majorDimension=ROWS`,
      {
        headers: { Authorization: `Bearer ${googleAccessToken}` },
      }
    );
    if (!valuesRes.ok) {
      const detail = await readErrorDetail(valuesRes);
      return `No se pudo leer celdas de la primera hoja: ${detail}`;
    }

    const valuesData = await valuesRes.json();
    const values = valuesData?.values as string[][] | undefined;
    if (!values || values.length === 0) {
      return `Sheet detectada: ${spreadsheetTitle} / ${firstSheetName}\nLa primera hoja no tiene datos en el rango A1:H12.`;
    }

    const header = values[0];
    const rows = values.slice(1, 11);
    const formatRow = (row: string[]) => row.map((c) => String(c ?? "").trim()).join(" | ");

    const lines = [
      `Vista previa de "${spreadsheetTitle}" -> hoja "${firstSheetName}"`,
      formatRow(header),
      ...rows.map(formatRow),
    ];
    return lines.join("\n");
  };

  const sendMessage = async () => {
    if (!prompt.trim() || !token || !activeProject || streaming) return;
    const userMsg: Message = { role: "user", content: prompt.trim() };
    const nextMessagesBase = [...messages, userMsg];
    setMessages(nextMessagesBase);
    setPrompt("");
    setStreaming(true);

    let nextMessages = nextMessagesBase;
    let llmMessages: Message[] = nextMessagesBase;
    const sheetMatch = prompt.trim().match(GOOGLE_SHEETS_URL_RE);
    if (sheetMatch) {
      try {
        const sheetUrl = sheetMatch[0];
        const previewText = await buildSheetPreview(sheetUrl);
        const previewMsg: Message = {
          role: "assistant",
          content: previewText,
        };
        nextMessages = [...nextMessagesBase, previewMsg];
        setMessages(nextMessages);
        llmMessages = [
          ...nextMessagesBase,
          {
            role: "system",
            content:
              "El usuario compartio una Google Sheet y ya fue leida por la aplicacion. " +
              "No digas que no puedes acceder enlaces. Usa solo la vista previa proporcionada " +
              "para responder y analizar datos.",
          },
          {
            role: "system",
            content: `Vista previa de la sheet:\n${previewText}`,
          },
        ];
      } catch (err) {
        const failMsg: Message = {
          role: "assistant",
          content: `No se pudo obtener vista previa de la Sheet: ${(err as Error).message}`,
        };
        nextMessages = [...nextMessagesBase, failMsg];
        setMessages(nextMessages);
        llmMessages = nextMessagesBase;
      }
    }

    const res = await fetch(`${BACKEND_BASE_URL}/chat/stream`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "text/event-stream",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({
        project_id: activeProject.id,
        project_name: activeProject.name,
        messages: llmMessages,
      }),
    });

    const contentType = res.headers.get("content-type") || "";
    if (contentType.includes("application/json")) {
      try {
        const data = await res.json();
        const detail = data?.detail || data?.message || "Respuesta JSON inesperada";
        setError(`Respuesta JSON inesperada: ${detail}`);
      } catch {
        setError("Respuesta JSON inesperada");
      }
      setStreaming(false);
      return;
    }

    if (!res.ok || !res.body) {
      if (await handleAuthError(res)) {
        setStreaming(false);
        return;
      }
      setError(`Error al enviar mensaje: ${res.status}`);
      setStreaming(false);
      return;
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let assistantText = "";
    let buffer = "";

    setMessages((prev) => [...prev, { role: "assistant", content: "" }]);

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      let lineEnd = buffer.indexOf("\n");
      while (lineEnd !== -1) {
        const line = buffer.slice(0, lineEnd).trimEnd();
        buffer = buffer.slice(lineEnd + 1);

        if (line.startsWith("data: ")) {
          const tokenChunk = line.slice(6);
          if (tokenChunk === "[DONE]") continue;
          assistantText += tokenChunk;
          setMessages((prev) => {
            const copy = [...prev];
            copy[copy.length - 1] = { role: "assistant", content: assistantText };
            return copy;
          });
        }
        lineEnd = buffer.indexOf("\n");
      }
    }

    setStreaming(false);
  };

  useEffect(() => {
    if (token) {
      loadProjects();
    } else {
      setProjects([]);
      setActiveProject(null);
      setMessages([]);
    }
    setProjectModalOpen(false);
    setProjectDraftName("");
    setProjectModalMode("create");
    setEditingProjectId(null);
    setProjectMenuOpenId(null);
    setAccountMenuOpen(false);
  }, [token]);

  useEffect(() => {
    if (activeProject) {
      loadMessages(activeProject);
    }
  }, [activeProject?.id]);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: streaming ? "smooth" : "auto" });
  }, [messages.length, streaming]);

  useEffect(() => {
    if (!accountMenuOpen) return;
    const onPointerDown = (event: MouseEvent) => {
      const container = accountMenuRef.current;
      if (!container) return;
      const target = event.target as Node;
      if (!container.contains(target)) {
        setAccountMenuOpen(false);
      }
    };
    document.addEventListener("mousedown", onPointerDown);
    return () => document.removeEventListener("mousedown", onPointerDown);
  }, [accountMenuOpen]);

  useEffect(() => {
    if (!projectMenuOpenId) return;
    const onPointerDown = (event: MouseEvent) => {
      const container = projectMenuRef.current;
      if (!container) return;
      const target = event.target as Node;
      if (!container.contains(target)) {
        setProjectMenuOpenId(null);
      }
    };
    document.addEventListener("mousedown", onPointerDown);
    return () => document.removeEventListener("mousedown", onPointerDown);
  }, [projectMenuOpenId]);

  useEffect(() => {
    if (!projectModalOpen) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setProjectModalOpen(false);
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [projectModalOpen]);

  return (
    <div className={styles.shell}>
      <aside className={styles.sidebar}>
        <div className={styles.sidebarTop}>
          <div className={styles.brand}>Research Copilot</div>

          {status === "loading" ? (
            <p className={styles.muted}>Cargando sesión...</p>
          ) : session ? (
            <>
              <button
                className={styles.newProjectLink}
                onClick={() => {
                  setProjectModalMode("create");
                  setEditingProjectId(null);
                  setProjectDraftName("");
                  setProjectModalOpen(true);
                }}
              >
                New Project
              </button>
              <div className={styles.projectSectionTitle}>Projects</div>
            </>
          ) : (
            <button className={styles.primary} onClick={() => signIn("google")}>
              Iniciar con Google
            </button>
          )}

          <div className={styles.projectList}>
            {projects.map((p) => (
              <div
                key={p.id}
                className={
                  activeProject?.id === p.id
                    ? `${styles.projectRow} ${styles.projectRowActive}`
                    : styles.projectRow
                }
              >
                <button
                  className={styles.projectItem}
                  onClick={() => setActiveProject(p)}
                >
                  {p.name}
                </button>
                <button
                  className={styles.projectMore}
                  onClick={(e) => {
                    e.stopPropagation();
                    setProjectMenuOpenId((current) => (current === p.id ? null : p.id));
                  }}
                  aria-label="Opciones de proyecto"
                >
                  ...
                </button>
                {projectMenuOpenId === p.id && (
                  <div className={styles.projectMenu} ref={projectMenuRef}>
                    <button
                      className={styles.projectMenuAction}
                      onClick={() => {
                        setProjectMenuOpenId(null);
                        setProjectModalMode("rename");
                        setEditingProjectId(p.id);
                        setProjectDraftName(p.name);
                        setProjectModalOpen(true);
                      }}
                    >
                      Rename
                    </button>
                    <button
                      className={`${styles.projectMenuAction} ${styles.projectMenuDanger}`}
                      onClick={() => {
                        setProjectMenuOpenId(null);
                        deleteProject(p.id);
                      }}
                    >
                      Delete
                    </button>
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>

        {session && (
          <div className={styles.accountArea} ref={accountMenuRef}>
            {accountMenuOpen && (
              <div className={styles.accountMenu}>
                <div className={styles.accountHeader}>
                  <div className={styles.accountAvatar}>{displayInitials}</div>
                  <div className={styles.accountText}>
                    <div className={styles.accountName}>{displayName}</div>
                    <div className={styles.accountEmail}>{displayEmail}</div>
                  </div>
                </div>
                <div className={styles.accountDivider} />
                {accountMenuItems.map((item) => (
                  <button
                    key={item.id}
                    className={styles.accountAction}
                    onClick={() => {
                      setAccountMenuOpen(false);
                      item.onClick();
                    }}
                  >
                    {item.label}
                  </button>
                ))}
              </div>
            )}

            <button
              className={styles.accountTrigger}
              onClick={() => setAccountMenuOpen((prev) => !prev)}
            >
              <div className={styles.accountAvatar}>{displayInitials}</div>
              <div className={styles.accountText}>
                <div className={styles.accountName}>{displayName}</div>
                <div className={styles.accountPlan}>Plus</div>
              </div>
            </button>
          </div>
        )}
      </aside>

      <main className={styles.main}>
        <header className={styles.header}>
          <div>
            <h1>{activeProject ? activeProject.name : "Sin proyecto"}</h1>
          </div>
        </header>

        {error && <div className={styles.error}>{error}</div>}
        <section className={styles.chatWindow}>
          <div className={styles.chatContent}>
            {loadingMessages ? (
              <p className={styles.muted}>Cargando mensajes...</p>
            ) : messages.length === 0 ? (
              <div className={styles.emptyState}>
                <h2>Empezá una conversación</h2>
                <p>Seleccioná un proyecto y escribí tu primer mensaje.</p>
              </div>
            ) : (
              messages.map((m, idx) => (
                <div
                  key={idx}
                  className={
                    m.role === "user"
                      ? `${styles.messageRow} ${styles.messageRowUser}`
                      : `${styles.messageRow} ${styles.messageRowAssistant}`
                  }
                >
                  <div
                    className={
                      m.role === "user"
                        ? `${styles.messageBubble} ${styles.messageBubbleUser}`
                        : `${styles.messageBubble} ${styles.messageBubbleAssistant}`
                    }
                  >
                    {m.content}
                  </div>
                </div>
              ))
            )}
            <div ref={chatEndRef} />
          </div>
        </section>

        <footer className={styles.composer}>
          <div className={styles.composerInner}>
            <input
              className={styles.composerInput}
              type="text"
              placeholder="Ask anything"
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") sendMessage();
              }}
              disabled={!activeProject}
            />
            <button
              className={styles.sendButton}
              onClick={sendMessage}
              disabled={!activeProject || streaming}
              aria-label="Enviar mensaje"
            >
              {streaming ? "…" : "↑"}
            </button>
          </div>
        </footer>
      </main>

      {projectModalOpen && (
        <div
          className={styles.modalOverlay}
          onClick={() => setProjectModalOpen(false)}
        >
          <div
            className={styles.projectModal}
            onClick={(e) => e.stopPropagation()}
          >
            <div className={styles.projectModalHeader}>
              <h3>{projectModalMode === "create" ? "Create project" : "Rename project"}</h3>
              <button
                className={styles.modalClose}
                onClick={() => setProjectModalOpen(false)}
              >
                x
              </button>
            </div>
            <input
              className={styles.projectModalInput}
              type="text"
              placeholder="Project name"
              value={projectDraftName}
              onChange={(e) => setProjectDraftName(e.target.value)}
              autoFocus
            />
            <button
              className={styles.projectModalCreate}
              onClick={() => {
                if (projectModalMode === "create") {
                  createProject(projectDraftName);
                  return;
                }
                if (editingProjectId) {
                  renameProject(editingProjectId, projectDraftName);
                }
              }}
              disabled={!projectDraftName.trim()}
            >
              {projectModalMode === "create" ? "Create project" : "Save"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
