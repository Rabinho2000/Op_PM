import { useEffect } from "react";
import { useNavigate } from "react-router-dom";
import ProjectDetail from "../pages/ProjectDetail";
import { Modal } from "./ui";

/**
 * Project detail rendered over a background route. The existing detail page
 * owns loading, tabs, permissions and edit forms; this wrapper only owns the
 * modal lifecycle and the refresh signal for the works calendar.
 */
export default function ProjectDetailOverlay() {
  const navigate = useNavigate();

  useEffect(() => {
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previousOverflow;
    };
  }, []);

  function close() {
    window.dispatchEvent(new CustomEvent("op:works-project-refresh"));
    navigate(-1);
  }

  return (
    <Modal title="Detalhe do projeto" onClose={close}>
      <ProjectDetail />
    </Modal>
  );
}
