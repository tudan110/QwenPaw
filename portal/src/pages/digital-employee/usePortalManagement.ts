import { useEffect, useState } from "react";
import { getPortalCapabilities } from "../../api/sso";

// The SSO monitor reloads the page when the verified account changes.
export function usePortalManagement(): boolean | null {
  const [canManageAi, setCanManageAi] = useState<boolean | null>(null);
  useEffect(() => {
    let controller: AbortController | undefined;
    const refresh = () => {
      controller?.abort();
      const current = new AbortController();
      controller = current;
      void getPortalCapabilities(current.signal).then(
        (capability) => {
          if (!current.signal.aborted) setCanManageAi(capability.can_manage_ai === true);
        },
        () => {
          if (!current.signal.aborted) setCanManageAi(false);
        },
      );
    };
    refresh();
    window.addEventListener("focus", refresh);
    return () => {
      window.removeEventListener("focus", refresh);
      controller?.abort();
    };
  }, []);
  return canManageAi;
}
