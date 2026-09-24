import { useState, type FC } from "react";
import { PhotoSlider } from "react-photo-view";
import "react-photo-view/dist/react-photo-view.css";
import { useTranslation } from "react-i18next";
import styles from "./index.module.less";

type Props = {
  src: string;
};

/** 当前页背景为图片时：Select 下方长条缩略图，点击用 PhotoSlider 全屏预览 */
export const BackgroundImageStrip: FC<Props> = ({ src }) => {
  const { t } = useTranslation();
  const [visible, setVisible] = useState(false);

  if (!src) return null;

  return (
    <>
      <button
        type="button"
        className={styles.bgImageBar}
        title={t("startPanel.previewBackgroundImage")}
        onClick={() => setVisible(true)}
      >
        <img src={src} alt="" draggable={false} />
      </button>

      <PhotoSlider
        images={[{ key: "page-background", src, overlay: <div /> }]}
        visible={visible}
        onClose={() => setVisible(false)}
      />
    </>
  );
};
