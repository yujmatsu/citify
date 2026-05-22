"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import {
  AGE_GROUPS,
  INTERESTS,
  type AgeGroup,
  type Interest,
  type Persona,
  savePersona,
} from "@/lib/persona";
import { cn } from "@/lib/utils";

const AGE_LABEL: Record<AgeGroup, string> = {
  "18-24": "18-24 歳",
  "25-29": "25-29 歳",
  "30-34": "30-34 歳",
  "35+": "35 歳以上",
};

const INTEREST_EMOJI: Record<Interest, string> = {
  住居: "🏠",
  雇用: "💼",
  結婚: "💍",
  子育て: "👶",
  税: "💰",
  起業: "🚀",
  防災: "🌊",
  医療: "🏥",
  教育: "📚",
  移住: "🚆",
};

export default function OnboardingPage() {
  const router = useRouter();
  const [step, setStep] = useState<1 | 2>(1);
  const [ageGroup, setAgeGroup] = useState<AgeGroup | null>(null);
  const [interests, setInterests] = useState<Set<Interest>>(new Set());

  function toggleInterest(i: Interest) {
    setInterests((prev) => {
      const next = new Set(prev);
      if (next.has(i)) next.delete(i);
      else next.add(i);
      return next;
    });
  }

  function handleNext() {
    if (step === 1 && ageGroup) setStep(2);
  }

  function handleFinish() {
    if (!ageGroup) return;
    const userId = `demo-${ageGroup}`;
    const persona: Persona = {
      user_id: userId,
      age_group: ageGroup,
      interests: Array.from(interests),
      // ハッカソンスコープ: 33000=岡山県, 00000=国会 を default (後で /municipalities で変更可)
      municipality_codes: ["33000", "00000"],
    };
    savePersona(persona);
    // step 2 終了後に自治体登録画面へ (A-2)、スキップしてフィードへ直行も可能
    router.push("/municipalities");
  }

  return (
    <main className="flex flex-1 flex-col items-center px-6 pt-16 pb-12">
      <div className="w-full max-w-md space-y-10">
        {/* Step indicator */}
        <div className="flex items-center justify-center gap-3 text-xs text-zinc-500">
          <span
            className={cn(
              step >= 1 ? "font-semibold text-zinc-900 dark:text-zinc-100" : "",
            )}
          >
            1. 年代
          </span>
          <span>—</span>
          <span
            className={cn(
              step >= 2 ? "font-semibold text-zinc-900 dark:text-zinc-100" : "",
            )}
          >
            2. 関心軸
          </span>
        </div>

        {step === 1 && (
          <section className="space-y-6">
            <header className="text-center space-y-2">
              <h1 className="text-2xl font-semibold tracking-tight">
                あなたの年代は？
              </h1>
              <p className="text-sm text-zinc-600 dark:text-zinc-400">
                年代に合わせた言葉遣いでお届けします
              </p>
            </header>
            <div className="grid grid-cols-2 gap-3">
              {AGE_GROUPS.map((ag) => (
                <button
                  key={ag}
                  type="button"
                  onClick={() => setAgeGroup(ag)}
                  className={cn(
                    "rounded-2xl border px-4 py-5 text-base font-medium transition-colors",
                    "hover:border-zinc-900 dark:hover:border-zinc-300",
                    ageGroup === ag
                      ? "border-zinc-900 bg-zinc-900 text-zinc-50 dark:border-zinc-100 dark:bg-zinc-100 dark:text-zinc-900"
                      : "border-zinc-300 bg-white text-zinc-900 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100",
                  )}
                >
                  {AGE_LABEL[ag]}
                </button>
              ))}
            </div>
            <button
              type="button"
              onClick={handleNext}
              disabled={!ageGroup}
              className={cn(
                "h-12 w-full rounded-full text-base font-medium transition-colors",
                ageGroup
                  ? "bg-zinc-900 text-zinc-50 hover:bg-zinc-800 dark:bg-zinc-50 dark:text-zinc-900 dark:hover:bg-zinc-200"
                  : "bg-zinc-200 text-zinc-400 cursor-not-allowed dark:bg-zinc-800 dark:text-zinc-600",
              )}
            >
              次へ
            </button>
          </section>
        )}

        {step === 2 && (
          <section className="space-y-6">
            <header className="text-center space-y-2">
              <h1 className="text-2xl font-semibold tracking-tight">
                気になるトピックは？
              </h1>
              <p className="text-sm text-zinc-600 dark:text-zinc-400">
                複数選択 OK・あとから変更可能です ({interests.size} 個選択中)
              </p>
            </header>
            <div className="grid grid-cols-2 gap-3">
              {INTERESTS.map((i) => (
                <button
                  key={i}
                  type="button"
                  onClick={() => toggleInterest(i)}
                  className={cn(
                    "flex items-center gap-2 rounded-2xl border px-4 py-4 text-base font-medium transition-colors",
                    interests.has(i)
                      ? "border-zinc-900 bg-zinc-900 text-zinc-50 dark:border-zinc-100 dark:bg-zinc-100 dark:text-zinc-900"
                      : "border-zinc-300 bg-white text-zinc-900 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100",
                  )}
                >
                  <span aria-hidden>{INTEREST_EMOJI[i]}</span>
                  <span>{i}</span>
                </button>
              ))}
            </div>
            <div className="flex gap-3">
              <button
                type="button"
                onClick={() => setStep(1)}
                className="h-12 flex-1 rounded-full border border-zinc-300 bg-transparent text-base font-medium transition-colors hover:bg-zinc-100 dark:border-zinc-700 dark:hover:bg-zinc-900"
              >
                戻る
              </button>
              <button
                type="button"
                onClick={handleFinish}
                className="h-12 flex-1 rounded-full bg-zinc-900 text-base font-medium text-zinc-50 transition-colors hover:bg-zinc-800 dark:bg-zinc-50 dark:text-zinc-900 dark:hover:bg-zinc-200"
              >
                次へ
              </button>
            </div>
          </section>
        )}
      </div>
    </main>
  );
}
