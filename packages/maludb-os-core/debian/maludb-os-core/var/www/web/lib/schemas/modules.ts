import { z } from "zod";

/** The contract with render_module_stub() in app/features/modules/stub.php — change both together. */
export const moduleStub = z.object({
  stub: z.object({
    key: z.string(),
    label: z.string(),
    icon: z.string(),
    phase: z.number().int(),
    phase_name: z.string().nullable(),
    module_grant: z.string().nullable(),
    url: z.string(),
    application: z.object({
      name: z.string().nullable(),
      description: z.string().nullable(),
      category: z.string().nullable(),
      location_name: z.string().nullable(),
      department_name: z.string().nullable(),
    }),
  }),
});

/**
 * Routes whose PHP endpoint is render_module_stub() — a module that is registered and designed
 * but not built. The catch-all renders these from PHP's stub payload. EMPTY since 2026-09-20:
 * all fourteen stubbed modules are built and have their own routes (My Work was the last). A
 * future module that is designed before it is built goes here until its route exists.
 */
export const STUB_PATHS: Record<string, string> = {};
