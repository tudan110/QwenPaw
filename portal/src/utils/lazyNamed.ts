import { lazy, type ComponentType } from "react";

export function lazyNamed<TModule extends Record<string, unknown>>(
  loader: () => Promise<TModule>,
  exportName: keyof TModule,
) {
  return lazy(async () => {
    const module = await loader();
    const component = module[exportName];

    if (!component) {
      throw new Error(`Missing lazy export: ${String(exportName)}`);
    }

    return { default: component as ComponentType<any> };
  });
}
