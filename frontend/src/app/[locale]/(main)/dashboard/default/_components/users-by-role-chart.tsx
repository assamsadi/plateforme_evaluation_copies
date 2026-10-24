"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  LabelList,
  type LabelProps,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { useTranslations } from "next-intl";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

const ROLE_COLORS = [
  "#10b981", // Étudiants - Emerald
  "#0ea5e9", // Professeurs - Sky
  "#6366f1", // Admins - Indigo
];

const renderCustomizedLabel = (props: LabelProps) => {
  const { x, y, width, value } = props;

  if (x == null || y == null || width == null || value == null) {
    return null;
  }
  const radius = 12;

  return (
    <g>
      <circle
        cx={Number(x) + Number(width) / 2}
        cy={Number(y) - radius - 6}
        r={radius}
        fill="#059669"
      />
      <text
        x={Number(x) + Number(width) / 2}
        y={Number(y) - radius - 5}
        fill="#ffffff"
        textAnchor="middle"
        dominantBaseline="middle"
        fontSize="11"
        fontWeight="bold"
      >
        {String(value)}
      </text>
    </g>
  );
};

export function UsersByRoleChart({
  title,
  usersByRole,
}: {
  title: string;
  usersByRole: {
    student: number;
    professor: number;
    admin: number;
  };
}) {
  const t = useTranslations("Overview");

  const total = usersByRole.student + usersByRole.professor + usersByRole.admin;

  const data = [
    {
      name: t("roleStudent"),
      count: usersByRole.student,
      fill: ROLE_COLORS[0],
    },
    {
      name: t("roleProfessor"),
      count: usersByRole.professor,
      fill: ROLE_COLORS[1],
    },
    {
      name: t("roleAdmin"),
      count: usersByRole.admin,
      fill: ROLE_COLORS[2],
    },
  ];

  return (
    <Card className="border-slate-200/90 shadow-2xs dark:border-zinc-800">
      <CardHeader className="flex flex-row items-center justify-between border-b border-slate-100 pb-3.5 dark:border-zinc-800">
        <CardTitle className="text-xl font-bold italic leading-none text-slate-900 dark:text-zinc-100">{title}</CardTitle>
        <span className="text-xs font-semibold italic text-black dark:text-zinc-200">
          {total} total
        </span>
      </CardHeader>
      <CardContent className="pt-5 pb-4">
        <div className="w-full h-64">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart
              data={data}
              margin={{
                top: 30,
                right: 16,
                left: -20,
                bottom: 5,
              }}
            >
              <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="var(--border)" opacity={0.6} />
              <XAxis
                dataKey="name"
                tickLine={false}
                axisLine={{ stroke: "var(--border)" }}
                tick={{ fontSize: 13, fontWeight: 600, fill: "var(--foreground)" }}
              />
              <YAxis
                tickLine={false}
                axisLine={false}
                tick={{ fontSize: 12, fill: "var(--muted-foreground)" }}
                allowDecimals={false}
              />
              <Tooltip
                cursor={{ fill: "rgba(0, 0, 0, 0.04)" }}
                content={({ active, payload }) => {
                  if (active && payload && payload.length) {
                    const item = payload[0].payload;
                    const percent = total > 0 ? Math.round((item.count / total) * 100) : 0;
                    return (
                      <div className="rounded-xl border border-slate-200 bg-white p-3 shadow-lg dark:border-zinc-800 dark:bg-zinc-900">
                        <p className="text-xs font-bold uppercase tracking-wider text-slate-500 dark:text-zinc-400">
                          {item.name}
                        </p>
                        <p className="mt-1 text-base font-bold text-slate-900 dark:text-zinc-100">
                          {item.count} utilisateur{item.count > 1 ? "s" : ""} ({percent}%)
                        </p>
                      </div>
                    );
                  }
                  return null;
                }}
              />
              <Bar
                dataKey="count"
                barSize={32}
                radius={[8, 8, 0, 0]}
                minPointSize={10}
              >
                <LabelList dataKey="count" content={renderCustomizedLabel} />
                {data.map((entry, index) => (
                  <Cell key={`cell-${index}`} fill={entry.fill} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </CardContent>
    </Card>
  );
}
