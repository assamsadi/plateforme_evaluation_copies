"use client";

import * as React from "react";
import { format } from "date-fns";
import { fr, enUS, es } from "date-fns/locale";
import { Calendar as CalendarIcon, Clock } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import { Calendar } from "@/components/ui/calendar";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { cn } from "@/lib/utils";

const localeMap: Record<string, typeof fr> = {
  fr,
  en: enUS,
  es,
};

interface DateTimePickerProps {
  value: string; // "YYYY-MM-DDTHH:mm" format (compatible with datetime-local)
  onChange: (value: string) => void;
  id?: string;
  disabled?: boolean;
  className?: string;
  placeholder?: string;
}

export function DateTimePicker({
  value,
  onChange,
  id,
  disabled = false,
  className,
  placeholder = "Choisir une date et heure",
}: DateTimePickerProps) {
  const currentLocale = useLocale();
  const dateLocale = localeMap[currentLocale] ?? fr;

  const [date, setDate] = React.useState<Date | undefined>(() => {
    if (!value) return undefined;
    const parsed = new Date(value);
    return isNaN(parsed.getTime()) ? undefined : parsed;
  });

  const [hours, setHours] = React.useState<string>(() => {
    if (!value) return "23";
    const parsed = new Date(value);
    return isNaN(parsed.getTime()) ? "23" : String(parsed.getHours()).padStart(2, "0");
  });

  const [minutes, setMinutes] = React.useState<string>(() => {
    if (!value) return "59";
    const parsed = new Date(value);
    return isNaN(parsed.getTime()) ? "59" : String(parsed.getMinutes()).padStart(2, "0");
  });

  const [isOpen, setIsOpen] = React.useState(false);

  // Sync internal state when external value changes
  React.useEffect(() => {
    if (!value) {
      setDate(undefined);
      return;
    }
    const parsed = new Date(value);
    if (!isNaN(parsed.getTime())) {
      setDate(parsed);
      setHours(String(parsed.getHours()).padStart(2, "0"));
      setMinutes(String(parsed.getMinutes()).padStart(2, "0"));
    }
  }, [value]);

  const updateValue = React.useCallback(
    (newDate: Date | undefined, newH: string, newM: string) => {
      if (!newDate) {
        onChange("");
        return;
      }
      const pad = (n: number) => String(n).padStart(2, "0");
      const yyyy = newDate.getFullYear();
      const mm = pad(newDate.getMonth() + 1);
      const dd = pad(newDate.getDate());
      onChange(`${yyyy}-${mm}-${dd}T${newH}:${newM}`);
    },
    [onChange]
  );

  const handleSelectDate = (selectedDay: Date | undefined) => {
    setDate(selectedDay);
    if (selectedDay) {
      updateValue(selectedDay, hours, minutes);
    }
  };

  const handleHourChange = (newHour: string) => {
    setHours(newHour);
    if (date) {
      updateValue(date, newHour, minutes);
    }
  };

  const handleMinuteChange = (newMinute: string) => {
    setMinutes(newMinute);
    if (date) {
      updateValue(date, hours, newMinute);
    }
  };

  // Generate 24 hours options
  const hourOptions = React.useMemo(() => {
    return Array.from({ length: 24 }, (_, i) => String(i).padStart(2, "0"));
  }, []);

  // Generate 5-minute interval options
  const minuteOptions = React.useMemo(() => {
    const mins = ["00", "05", "10", "15", "20", "25", "30", "35", "40", "45", "50", "55", "59"];
    return mins;
  }, []);

  return (
    <div className={cn("relative flex w-full flex-col gap-2", className)}>
      <Popover open={isOpen} onOpenChange={setIsOpen}>
        <PopoverTrigger asChild>
          <Button
            id={id}
            type="button"
            variant="outline"
            disabled={disabled}
            className={cn(
              "group h-11 w-full justify-start rounded-xl border-slate-200 bg-white px-3.5 text-left font-normal shadow-xs transition-all hover:border-emerald-500/50 hover:bg-slate-50/80 focus:border-emerald-500 focus:ring-4 focus:ring-emerald-500/20 dark:border-zinc-700 dark:bg-zinc-800 dark:hover:bg-zinc-800/80",
              !date && "text-slate-400 dark:text-zinc-500"
            )}
          >
            <div className="flex size-7 items-center justify-center rounded-lg border border-emerald-500/20 bg-emerald-50 text-emerald-600 transition-colors group-hover:bg-emerald-100/70 dark:bg-emerald-950/40 dark:text-emerald-400">
              <CalendarIcon className="size-4" />
            </div>
            <span className="ml-2.5 flex-1 truncate text-sm font-semibold text-slate-800 dark:text-zinc-100">
              {date ? (
                format(date, "PPP", { locale: dateLocale }) + ` à ${hours}:${minutes}`
              ) : (
                <span>{placeholder}</span>
              )}
            </span>
            <div className="flex items-center gap-1 rounded-md border border-slate-200 bg-slate-50 px-2 py-0.5 text-xs font-semibold text-slate-600 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-400">
              <Clock className="size-3" />
              <span>{hours}:{minutes}</span>
            </div>
          </Button>
        </PopoverTrigger>

        <PopoverContent
          align="start"
          className="w-auto rounded-2xl border border-slate-200/90 bg-white p-4 shadow-xl ring-1 ring-black/5 dark:border-zinc-700 dark:bg-zinc-900 dark:ring-white/10"
        >
          {/* Calendar Picker */}
          <div className="flex flex-col items-center">
            <Calendar
              mode="single"
              selected={date}
              onSelect={handleSelectDate}
              locale={dateLocale}
              autoFocus
              className="rounded-xl border-0 p-0"
            />

            {/* Time Selector */}
            <div className="mt-4 flex w-full items-center justify-between gap-3 border-t border-slate-100 pt-3 dark:border-zinc-800">
              <div className="flex items-center gap-2 text-xs font-semibold text-slate-600 dark:text-zinc-300">
                <Clock className="size-4 text-emerald-600 dark:text-emerald-400" />
                <span>Heure limite</span>
              </div>

              <div className="flex items-center gap-1.5">
                <Select value={hours} onValueChange={handleHourChange}>
                  <SelectTrigger className="h-9 w-18 rounded-lg border-slate-200 bg-slate-50 text-xs font-bold text-slate-800 shadow-none dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-100">
                    <SelectValue placeholder="HH" />
                  </SelectTrigger>
                  <SelectContent className="max-h-48 rounded-xl">
                    {hourOptions.map((h) => (
                      <SelectItem key={h} value={h} className="text-xs font-medium">
                        {h} h
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>

                <span className="font-bold text-slate-400">:</span>

                <Select value={minutes} onValueChange={handleMinuteChange}>
                  <SelectTrigger className="h-9 w-18 rounded-lg border-slate-200 bg-slate-50 text-xs font-bold text-slate-800 shadow-none dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-100">
                    <SelectValue placeholder="MM" />
                  </SelectTrigger>
                  <SelectContent className="max-h-48 rounded-xl">
                    {minuteOptions.map((m) => (
                      <SelectItem key={m} value={m} className="text-xs font-medium">
                        {m} min
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>

            {/* Quick shortcuts */}
            <div className="mt-3 flex w-full gap-2 border-t border-slate-100 pt-3 dark:border-zinc-800">
              <Button
                type="button"
                variant="ghost"
                size="xs"
                className="flex-1 rounded-lg text-xs font-semibold text-slate-600 hover:bg-slate-100 dark:text-zinc-300"
                onClick={() => {
                  const today = new Date();
                  setDate(today);
                  updateValue(today, "23", "59");
                  setHours("23");
                  setMinutes("59");
                }}
              >
                Aujourd'hui
              </Button>
              <Button
                type="button"
                variant="ghost"
                size="xs"
                className="flex-1 rounded-lg text-xs font-semibold text-slate-600 hover:bg-slate-100 dark:text-zinc-300"
                onClick={() => {
                  const nextWeek = new Date();
                  nextWeek.setDate(nextWeek.getDate() + 7);
                  setDate(nextWeek);
                  updateValue(nextWeek, "23", "59");
                  setHours("23");
                  setMinutes("59");
                }}
              >
                +7 jours
              </Button>
              <Button
                type="button"
                size="xs"
                className="rounded-lg bg-emerald-600 px-3 text-xs font-bold text-white hover:bg-emerald-700"
                onClick={() => setIsOpen(false)}
              >
                OK
              </Button>
            </div>
          </div>
        </PopoverContent>
      </Popover>
    </div>
  );
}
