import NextLink from "next/link";
import type { ComponentProps } from "react";

/**
 * The only link component screens use. Prefetch is OFF: a prefetch renders the target on the
 * server, which reads its PHP endpoint — and although an unmarked read is not logged as a
 * screen view, speculative reads of gated business data are not something to do by default.
 */
export default function Link(props: ComponentProps<typeof NextLink>) {
  return <NextLink prefetch={false} {...props} />;
}
