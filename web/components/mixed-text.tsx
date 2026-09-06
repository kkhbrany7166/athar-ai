import { Fragment } from "react";

/** Isolate Latin entity/technical runs in Arabic text without changing any bytes. */
export function MixedText({ text }: { text: string }) {
  if (!/[\u0600-\u06ff]/u.test(text)) return <>{text}</>;
  const runs =
    /[A-Za-z][A-Za-z0-9]*(?:[._/+&-][A-Za-z0-9]+)*(?:[ \t]+[A-Za-z0-9]+(?:[._/+&-][A-Za-z0-9]+)*)*[.,;:!?،؛؟]?/g;
  const parts = [];
  let offset = 0;
  for (const match of text.matchAll(runs)) {
    parts.push(
      <Fragment key={`text-${offset}`}>
        {text.slice(offset, match.index)}
      </Fragment>,
    );
    parts.push(
      <bdi className="mixed-latin" dir="ltr" key={`latin-${match.index}`}>
        {match[0]}
      </bdi>,
    );
    offset = match.index + match[0].length;
  }
  parts.push(<Fragment key={`text-${offset}`}>{text.slice(offset)}</Fragment>);
  return <>{parts}</>;
}
