import { useEffect, useState } from "react";
import { Avatar } from "antd";

import { resolveAssetUrl } from "../api";

interface AgentAvatarProps {
  name: string;
  path?: string | null;
  size?: number;
}

export function AgentAvatar({ name, path, size = 34 }: AgentAvatarProps) {
  const [source, setSource] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    void resolveAssetUrl(path)
      .then((url) => {
        if (active) setSource(url);
      })
      .catch(() => {
        if (active) setSource(null);
      });
    return () => {
      active = false;
    };
  }, [path]);

  return (
    <Avatar src={source ?? undefined} size={size} shape="square">
      {name.slice(0, 1)}
    </Avatar>
  );
}
