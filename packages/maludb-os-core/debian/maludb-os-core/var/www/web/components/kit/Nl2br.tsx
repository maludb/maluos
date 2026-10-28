import { Fragment } from "react";

/** nl2br(e($text)) — user text with its line breaks kept, and nothing else interpreted. */
export default function Nl2br({ text }: { text: string }) {
  const lines = text.split(/\r\n|\r|\n/);
  return (
    <>
      {lines.map((line, i) => (
        <Fragment key={i}>
          {line}
          {i < lines.length - 1 && <br />}
        </Fragment>
      ))}
    </>
  );
}
