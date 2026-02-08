"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { signIn, signOut, useSession } from "next-auth/react";
import styles from "./page.module.css";

const BACKEND_BASE_URL = process.env.NEXT_PUBLIC_BACKEND_BASE_URL || "http://127.0.0.1:8000";

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
  const [loadingProjects, setLoadingProjects] = useState(false);
  const [loadingMessages, setLoadingMessages] = useState(false);
  const [streaming, setStreaming] = useState(false);
  const [newProjectName, setNewProjectName] = useState("");
  const chatEndRef = useRef<HTMLDivElement | null>(null);

  const token = session?.id_token;

  const userId = useMemo(() => {
    return session?.user?.email ?? "";
  }, [session]);

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
    setLoadingProjects(true);
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
    } finally {
      setLoadingProjects(false);
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

  const createProject = async () => {
    if (!newProjectName.trim() || !token) return;
    setError(null);
    try {
      const res = await fetch(`${BACKEND_BASE_URL}/projects`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ name: newProjectName.trim() }),
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
      setNewProjectName("");
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const sendMessage = async () => {
    if (!prompt.trim() || !token || !activeProject || streaming) return;
    const userMsg: Message = { role: "user", content: prompt.trim() };
    const nextMessages = [...messages, userMsg];
    setMessages(nextMessages);
    setPrompt("");
    setStreaming(true);

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
        messages: nextMessages,
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
  }, [token]);

  useEffect(() => {
    if (activeProject) {
      loadMessages(activeProject);
    }
  }, [activeProject?.id]);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: streaming ? "smooth" : "auto" });
  }, [messages.length, streaming]);

  return (
    <div className={styles.shell}>
      <aside className={styles.sidebar}>
        <div className={styles.brand}>Research Copilot</div>

        {status === "loading" ? (
          <p className={styles.muted}>Cargando sesión...</p>
        ) : session ? (
          <>
            <div className={styles.sessionRow}>
              <span className={styles.sessionEmail}>{session.user?.email}</span>
              <button className={styles.ghost} onClick={() => signOut()}>
                Salir
              </button>
            </div>
            <div className={styles.newProjectRow}>
              <input
                className={styles.input}
                type="text"
                placeholder="Nuevo proyecto"
                value={newProjectName}
                onChange={(e) => setNewProjectName(e.target.value)}
              />
              <button className={styles.primary} onClick={createProject}>
                Crear
              </button>
            </div>
          </>
        ) : (
          <button className={styles.primary} onClick={() => signIn("google")}>
            Iniciar con Google
          </button>
        )}

        <button
          className={styles.secondary}
          onClick={loadProjects}
          disabled={!token || loadingProjects}
        >
          {loadingProjects ? "Cargando..." : "Recargar"}
        </button>

        <div className={styles.projectList}>
          {projects.map((p) => (
            <button
              key={p.id}
              className={
                activeProject?.id === p.id
                  ? `${styles.projectItem} ${styles.projectItemActive}`
                  : styles.projectItem
              }
              onClick={() => setActiveProject(p)}
            >
              {p.name}
            </button>
          ))}
        </div>
      </aside>

      <main className={styles.main}>
        <header className={styles.header}>
          <div>
            <h1>Chat</h1>
            <p className={styles.muted}>
              {activeProject ? `Proyecto: ${activeProject.name}` : "Sin proyecto"}
            </p>
          </div>
        </header>

        {error && <div className={styles.error}>{error}</div>}

        <section className={styles.chatWindow}>
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
                    ? `${styles.message} ${styles.messageUser}`
                    : `${styles.message} ${styles.messageAssistant}`
                }
              >
                <div className={styles.messageRole}>{m.role}</div>
                <div className={styles.messageContent}>{m.content}</div>
              </div>
            ))
          )}
          <div ref={chatEndRef} />
        </section>

        <footer className={styles.composer}>
          <div className={styles.composerInner}>
            <input
              className={styles.composerInput}
              type="text"
              placeholder="Escribí tu mensaje..."
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") sendMessage();
              }}
              disabled={!activeProject}
            />
            <button
              className={styles.primary}
              onClick={sendMessage}
              disabled={!activeProject || streaming}
            >
              {streaming ? "Enviando..." : "Enviar"}
            </button>
          </div>
          <p className={styles.hint}>Presioná Enter para enviar.</p>
        </footer>
      </main>
    </div>
  );
}
