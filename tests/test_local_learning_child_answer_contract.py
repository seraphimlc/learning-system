from pathlib import Path
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class LocalLearningChildAnswerContractTests(unittest.TestCase):
    def test_photo_copy_has_stable_required_and_optional_targets(self) -> None:
        html = (PROJECT_ROOT / "app/local_learning_system/index.html").read_text(encoding="utf-8")

        self.assertIn('id="childAnswerPhotoLabel"', html)
        self.assertIn('id="childAnswerPhotoHint"', html)
        self.assertIn('id="childAnswerPhotoMeta"', html)
        self.assertIn("可选：需要时补一张纸面过程", html)

    def test_photo_primary_is_required_without_exposing_text_surfaces(self) -> None:
        script = (PROJECT_ROOT / "app/local_learning_system/app.js").read_text(encoding="utf-8")

        self.assertIn('String(step?.answer_input_mode || "") === "photo"', script)
        self.assertIn('photoInput.required = requirePhotoNow', script)
        self.assertIn('"拍纸面答案（必答）"', script)
        self.assertIn('"照片就是本题答案，保存前请确认清楚完整。"', script)
        self.assertIn('if (photoRequired && !state.pendingEvidence.photoDataUrl && !state.v3Stuck)', script)
        self.assertIn('"请先拍下这道题完整、清楚的纸面作答"', script)
        self.assertIn('typed: Boolean(showForm && !photoRequired)', script)
        self.assertIn('interactionPanel.hidden = photoRequired', script)

    def test_structured_answer_only_does_not_offer_supplemental_explanation(self) -> None:
        script = (PROJECT_ROOT / "app/local_learning_system/app.js").read_text(encoding="utf-8")

        self.assertGreaterEqual(
            script.count("isShortText || normalizedInteraction.requires_explanation"),
            2,
        )
        self.assertNotIn("isShortText || normalizedInteraction.allow_explanation", script)
        self.assertIn(': "请写一句理由"', script)
        self.assertNotIn("可以补一句理由或检查方法", script)
        self.assertNotIn('"（可选）"', script)

    def test_expert_review_obeys_signed_answer_only_sufficiency(self) -> None:
        prompt = (
            PROJECT_ROOT / "learning_system/prompts/admin_question_expert_review.v1.md"
        ).read_text(encoding="utf-8")

        self.assertIn("signed slot `answer_only_sufficiency`", prompt)
        self.assertIn("When it is `sufficient`", prompt)
        self.assertIn("do not require extra steps, explanation, verification", prompt)
        self.assertIn(
            "when the signed `answer_only_sufficiency` is `insufficient`",
            prompt,
        )
        self.assertNotIn("- scoring cannot distinguish understanding from answer-only;", prompt)


if __name__ == "__main__":
    unittest.main()
