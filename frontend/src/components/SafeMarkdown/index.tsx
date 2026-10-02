import { type FC, type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import rehypeSanitize, { defaultSchema } from "rehype-sanitize";

/** Strict schema: no raw HTML tags beyond markdown-derived elements; no images/iframes. */
const schema = {
  ...defaultSchema,
  tagNames: (defaultSchema.tagNames || []).filter(
    (tag) =>
      ![
        "img",
        "iframe",
        "object",
        "embed",
        "script",
        "style",
        "form",
        "input",
        "button",
        "video",
        "audio",
        "source",
      ].includes(tag),
  ),
  protocols: {
    ...defaultSchema.protocols,
    href: ["http", "https", "mailto"],
  },
  attributes: {
    ...defaultSchema.attributes,
    a: [...((defaultSchema.attributes?.a as string[]) || []), "rel", "target"],
    code: [...((defaultSchema.attributes?.code as string[]) || []), "className"],
  },
};

type Props = {
  children: string;
  className?: string;
};

function safeHref(href: string | undefined): string | undefined {
  if (!href) return undefined;
  const trimmed = href.trim();
  if (/^(https?:|mailto:)/i.test(trimmed)) return trimmed;
  if (trimmed.startsWith("/") && !trimmed.startsWith("//")) return trimmed;
  return undefined;
}

export const SafeMarkdown: FC<Props> = ({ children, className }) => {
  return (
    <div className={className}>
      <ReactMarkdown
        rehypePlugins={[[rehypeSanitize, schema]]}
        skipHtml
        components={{
          a: ({ href, children: linkChildren }) => {
            const safe = safeHref(href);
            if (!safe) {
              return <span>{linkChildren as ReactNode}</span>;
            }
            return (
              <a href={safe} target="_blank" rel="noopener noreferrer">
                {linkChildren as ReactNode}
              </a>
            );
          },
          img: () => null,
        }}
      >
        {children}
      </ReactMarkdown>
    </div>
  );
};

export default SafeMarkdown;
