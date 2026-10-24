"use client";

import { useState } from "react";

import { IconSend2, IconSparkles } from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import { useSearchParams } from "next/navigation";

import {
  InputGroup,
  InputGroupAddon,
  InputGroupButton,
  InputGroupTextarea,
} from "@/components/ui/input-group";
import {
  Message,
  MessageAvatar,
  MessageContent,
} from "@/components/ui/message";
import {
  MessageScroller,
  MessageScrollerContent,
  MessageScrollerItem,
  MessageScrollerProvider,
  MessageScrollerViewport,
} from "@/components/ui/message-scroller";
import { Spinner } from "@/components/ui/spinner";
import { AuthApiError, getStoredSession } from "@/lib/auth-api";
import { askNotebookChat, type RecommendedExerciseRead } from "@/lib/student-api";

interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  text: string;
}

// Le chat NotebookLM est stateless côté nous — chaque question est un
// simple POST proxié vers client.chat.ask(notebook_id, question)
// (notebooklm_service.ask_chat) : c'est NotebookLM qui garde le contexte
// de conversation côté serveur (par notebook_id), jamais nous. La liste
// ci-dessous n'existe que pour l'affichage.
// Conversation d'exemple, affichée uniquement avec ?demoChat=1 dans l'URL
// (captures d'écran / soutenance) — jamais en usage normal.
const DEMO_CHAT: ChatMessage[] = [
  { id: "demo-1", role: "user", text: "Comment décrire les étapes de mon algorithme ?" },
  {
    id: "demo-2",
    role: "assistant",
    text: "Pour structurer ta démarche, commence par écrire 4 à 6 étapes en phrases courtes, avant tout calcul ou diagramme. Vérifie ensuite que chaque étape utilise uniquement des données déjà produites par les étapes précédentes. Dans ta dernière copie, quelle étape dépendait d'un résultat que tu n'avais pas encore calculé ?",
  },
  { id: "demo-3", role: "user", text: "C'était l'étape où je choisis le sommet de départ, je l'ai fait après le parcours." },
  {
    id: "demo-4",
    role: "assistant",
    text: "Exactement : le sommet de départ est une donnée d'entrée, il doit donc apparaître dans la toute première étape. Un bon schéma reprend tes étapes écrites : une boîte par étape, une flèche par dépendance. Peux-tu essayer de dessiner le parcours en largeur d'un petit graphe de 5 sommets ?",
  },
  { id: "demo-5", role: "user", text: "Quelle est la complexité d'un parcours en largeur ?" },
  {
    id: "demo-6",
    role: "assistant",
    text: "Pour la complexité, compte d'abord les opérations élémentaires par itération, puis multiplie par le nombre d'itérations. Pour un parcours de graphe, chaque sommet et chaque arête sont traités une seule fois : que te donne cela comme ordre de grandeur ?",
  },
];

export function ChatPanel({ recommendation }: { recommendation: RecommendedExerciseRead }) {
  const t = useTranslations("NotebookSheet");
  const searchParams = useSearchParams();
  // Les notebooks de démonstration sont les seuls dont les cartes mémoire
  // arrivent en URL "data:" (cf. notebook_demo_content.py côté API).
  const isDemoNotebook = Boolean(recommendation.flashcards_url?.startsWith("data:"));
  const [messages, setMessages] = useState<ChatMessage[]>(() =>
    isDemoNotebook || searchParams.get("demoChat") === "1" ? DEMO_CHAT : [],
  );
  const [question, setQuestion] = useState("");
  const [isAsking, setIsAsking] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSend(override?: string) {
    const trimmed = (override ?? question).trim();
    if (!trimmed || isAsking) return;

    const session = getStoredSession();
    if (!session) return;

    const userMessage: ChatMessage = { id: crypto.randomUUID(), role: "user", text: trimmed };
    setMessages((prev) => [...prev, userMessage]);
    setQuestion("");
    setError(null);
    setIsAsking(true);
    try {
      const answer = await askNotebookChat(session.accessToken, recommendation.student_id, recommendation.id, trimmed);
      setMessages((prev) => [...prev, { id: crypto.randomUUID(), role: "assistant", text: answer }]);
    } catch (askError) {
      setError(askError instanceof AuthApiError ? askError.message : t("chatError"));
    } finally {
      setIsAsking(false);
    }
  }

  // Suggestions cliquables — aident à démarrer la conversation plutôt
  // qu'un champ vide + une invite générique seuls (envoi direct au clic,
  // pas juste un pré-remplissage, pour un vrai démarrage rapide).
  const suggestions = [t("chatSuggestion1"), t("chatSuggestion2"), t("chatSuggestion3")];

  return (
    <div className="flex h-full min-h-0 flex-col">
      <MessageScrollerProvider autoScroll defaultScrollPosition="end">
        <MessageScroller className="flex-1">
          <MessageScrollerViewport>
          <MessageScrollerContent className="mx-auto w-full max-w-2xl px-4 py-6 md:px-6">
            {messages.length === 0 ? (
              <div className="flex h-full flex-col items-center justify-center gap-3 py-16 text-center">
                <div className="flex size-12 items-center justify-center rounded-full border border-primary/20 bg-primary/10 text-primary">
                  <IconSparkles className="size-5" stroke={1.75} />
                </div>
                <p className="max-w-xs text-sm text-muted-foreground">{t("chatEmptyState")}</p>
                <div className="mt-2 flex flex-wrap items-center justify-center gap-2">
                  {suggestions.map((suggestion) => (
                    <button
                      key={suggestion}
                      type="button"
                      onClick={() => handleSend(suggestion)}
                      className="rounded-full border border-primary/20 bg-primary/5 px-3.5 py-1.5 text-xs font-semibold text-primary transition-colors hover:bg-primary/10"
                    >
                      {suggestion}
                    </button>
                  ))}
                </div>
              </div>
            ) : (
              messages.map((message) => (
                <MessageScrollerItem key={message.id}>
                  <Message align={message.role === "user" ? "end" : "start"}>
                    <MessageAvatar
                      className={
                        message.role === "user"
                          ? "size-8 bg-primary text-xs font-bold text-primary-foreground"
                          : "size-8 bg-muted text-primary"
                      }
                    >
                      {message.role === "user" ? t("chatYouInitial") : <IconSparkles className="size-4" stroke={1.75} />}
                    </MessageAvatar>
                    <MessageContent>
                      <div
                        className={
                          message.role === "user"
                            ? "rounded-2xl bg-primary px-4 py-2.5 text-sm leading-relaxed text-primary-foreground"
                            : "rounded-2xl border border-primary/15 bg-primary/5 px-4 py-2.5 text-sm leading-relaxed text-foreground"
                        }
                      >
                        {message.text}
                      </div>
                    </MessageContent>
                  </Message>
                </MessageScrollerItem>
              ))
            )}

            {isAsking ? (
              <MessageScrollerItem scrollAnchor>
                <Message align="start">
                  <MessageAvatar className="size-8 bg-muted text-primary">
                    <IconSparkles className="size-4" stroke={1.75} />
                  </MessageAvatar>
                  <MessageContent>
                    <div className="flex items-center gap-2 rounded-2xl border border-primary/15 bg-primary/5 px-4 py-2.5 text-sm text-muted-foreground">
                      <Spinner className="size-3.5" />
                      {t("chatAsking")}
                    </div>
                  </MessageContent>
                </Message>
              </MessageScrollerItem>
            ) : null}
          </MessageScrollerContent>
          </MessageScrollerViewport>
        </MessageScroller>
      </MessageScrollerProvider>

      <div className="shrink-0 border-t border-border/60 p-4 md:p-6">
        {error ? <p className="mb-2 text-xs font-medium text-destructive">{error}</p> : null}
        <InputGroup className="mx-auto h-auto max-w-2xl">
          <InputGroupTextarea
            placeholder={t("chatPlaceholder")}
            value={question}
            rows={1}
            onChange={(event) => setQuestion(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                handleSend();
              }
            }}
          />
          <InputGroupAddon align="inline-end">
            <InputGroupButton
              size="icon-sm"
              variant="default"
              disabled={!question.trim() || isAsking}
              onClick={() => handleSend()}
              aria-label={t("chatSendAction")}
            >
              {isAsking ? <Spinner className="size-3.5" /> : <IconSend2 className="size-3.5" stroke={1.75} />}
            </InputGroupButton>
          </InputGroupAddon>
        </InputGroup>
      </div>
    </div>
  );
}
