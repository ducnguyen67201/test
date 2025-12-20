"use client";

import { useState } from "react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import {
  Plus,
  Check,
  Zap,
  Crown,
  Building2,
  ArrowRight,
  MoreHorizontal,
  Info,
} from "lucide-react";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { cn } from "@/lib/utils";

type PlanType = "free" | "pro" | "enterprise";

interface Plan {
  id: PlanType;
  name: string;
  description: string;
  price: string;
  period: string;
  features: string[];
  icon: React.ComponentType<{ className?: string }>;
  popular?: boolean;
}

const plans: Plan[] = [
  {
    id: "free",
    name: "Free",
    description: "For individuals getting started",
    price: "$0",
    period: "forever",
    icon: Zap,
    features: [
      "Up to 3 lab environments",
      "Basic CVE database access",
      "Community support",
      "1 hour lab sessions",
    ],
  },
  {
    id: "pro",
    name: "Pro",
    description: "For security professionals",
    price: "$29",
    period: "per month",
    icon: Crown,
    popular: true,
    features: [
      "Unlimited lab environments",
      "Full CVE database access",
      "Priority support",
      "Unlimited session duration",
      "Custom lab configurations",
      "Team collaboration (up to 5)",
    ],
  },
  {
    id: "enterprise",
    name: "Enterprise",
    description: "For organizations & teams",
    price: "Custom",
    period: "contact us",
    icon: Building2,
    features: [
      "Everything in Pro",
      "Unlimited team members",
      "SSO / SAML integration",
      "Dedicated infrastructure",
      "Custom integrations",
      "24/7 support & SLA",
    ],
  },
];

type CardBrand = "visa" | "mastercard" | "amex";
type CardColor = "dark" | "orange" | "blue" | "purple";

interface PaymentMethod {
  id: string;
  type: "card";
  brand: CardBrand;
  last4: string;
  expiryMonth: number;
  expiryYear: number;
  cardholderName: string;
  isDefault: boolean;
  color: CardColor;
}

const cardColors: Record<CardColor, string> = {
  dark: "bg-gradient-to-br from-gray-800 to-gray-900",
  orange: "bg-gradient-to-br from-orange-500 to-orange-600",
  blue: "bg-gradient-to-br from-blue-500 to-blue-600",
  purple: "bg-gradient-to-br from-purple-500 to-purple-600",
};

function CardBrandLogo({ brand }: { brand: CardBrand }) {
  if (brand === "mastercard") {
    return (
      <div className="flex">
        <div className="h-6 w-6 rounded-full bg-red-500 opacity-90" />
        <div className="h-6 w-6 rounded-full bg-yellow-500 opacity-90 -ml-2" />
      </div>
    );
  }
  if (brand === "visa") {
    return (
      <span className="text-white font-bold text-lg italic">VISA</span>
    );
  }
  if (brand === "amex") {
    return (
      <span className="text-white font-bold text-sm">AMEX</span>
    );
  }
  return null;
}

function CreditCardVisual({
  card,
  onSetDefault,
  onRemove,
}: {
  card: PaymentMethod;
  onSetDefault: () => void;
  onRemove: () => void;
}) {
  const expiry = `${card.expiryMonth.toString().padStart(2, "0")}/${card.expiryYear.toString().slice(-2)}`;

  return (
    <div
      className={cn(
        "relative w-full aspect-[1.586/1] max-w-[280px] rounded-xl p-4 text-white shadow-lg",
        cardColors[card.color]
      )}
    >
      {/* Card brand logo */}
      <div className="flex items-start justify-between">
        <CardBrandLogo brand={card.brand} />
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button className="text-white/80 hover:text-white transition-colors">
              <MoreHorizontal className="h-5 w-5" />
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem onClick={onSetDefault} disabled={card.isDefault}>
              Set as default
            </DropdownMenuItem>
            <DropdownMenuItem onClick={onRemove} className="text-destructive">
              Remove card
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>

      {/* Card details */}
      <div className="absolute bottom-4 left-4 right-4">
        <div className="flex items-end justify-between mb-3">
          <p className="text-xs font-medium uppercase tracking-wider opacity-90">
            {card.cardholderName}
          </p>
          <p className="text-sm font-medium">{expiry}</p>
        </div>
        <div className="flex items-center gap-2 text-sm font-mono tracking-widest">
          <span className="opacity-70">****</span>
          <span className="opacity-70">****</span>
          <span className="opacity-70">****</span>
          <span>{card.last4}</span>
        </div>
      </div>
    </div>
  );
}

function AddCardPlaceholder({ onClick }: { onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className="w-full aspect-[1.586/1] max-w-[280px] rounded-xl border-2 border-dashed border-muted-foreground/25 bg-muted/30 flex flex-col items-center justify-center gap-2 hover:border-muted-foreground/50 hover:bg-muted/50 transition-colors"
    >
      <div className="h-10 w-10 rounded-full bg-muted flex items-center justify-center">
        <Plus className="h-5 w-5 text-muted-foreground" />
      </div>
      <span className="text-sm text-muted-foreground">Add another card</span>
    </button>
  );
}

// Sample cards for demo - in production, fetch from API
const sampleCards: PaymentMethod[] = [
  {
    id: "1",
    type: "card",
    brand: "mastercard",
    last4: "6827",
    expiryMonth: 12,
    expiryYear: 2025,
    cardholderName: "John Doe",
    isDefault: true,
    color: "dark",
  },
  {
    id: "2",
    type: "card",
    brand: "mastercard",
    last4: "2998",
    expiryMonth: 7,
    expiryYear: 2025,
    cardholderName: "John Doe",
    isDefault: false,
    color: "orange",
  },
];

export function PaymentSettings() {
  const [currentPlan] = useState<PlanType>("free");
  const [paymentMethods, setPaymentMethods] = useState<PaymentMethod[]>(sampleCards);

  const handleSetDefault = (cardId: string) => {
    setPaymentMethods((prev) =>
      prev.map((card) => ({
        ...card,
        isDefault: card.id === cardId,
      }))
    );
  };

  const handleRemoveCard = (cardId: string) => {
    setPaymentMethods((prev) => prev.filter((card) => card.id !== cardId));
  };

  const handleAddCard = () => {
    // In production, open a modal or redirect to payment provider
    console.log("Add card clicked");
  };

  const defaultCard = paymentMethods.find((card) => card.isDefault);

  return (
    <div className="space-y-6">
      {/* Current Plan */}
      <Card>
        <CardHeader>
          <CardTitle>Current Plan</CardTitle>
          <CardDescription>
            You are currently on the{" "}
            <span className="font-medium text-foreground capitalize">
              {currentPlan}
            </span>{" "}
            plan.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex items-center gap-4">
            <div className="flex h-12 w-12 items-center justify-center rounded-lg bg-primary/10">
              <Zap className="h-6 w-6 text-primary" />
            </div>
            <div>
              <p className="font-medium">Free Plan</p>
              <p className="text-sm text-muted-foreground">
                Basic features for personal use
              </p>
            </div>
            <Badge variant="secondary" className="ml-auto">
              Active
            </Badge>
          </div>
        </CardContent>
      </Card>

      {/* Upgrade Plans */}
      <Card>
        <CardHeader>
          <CardTitle>Upgrade Your Plan</CardTitle>
          <CardDescription>
            Choose a plan that fits your needs.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid gap-4 md:grid-cols-3">
            {plans.map((plan) => {
              const isCurrentPlan = plan.id === currentPlan;
              return (
                <div
                  key={plan.id}
                  className={cn(
                    "relative flex flex-col rounded-lg border p-4",
                    plan.popular && "border-primary shadow-sm",
                    isCurrentPlan && "bg-accent/50"
                  )}
                >
                  {plan.popular && (
                    <Badge className="absolute -top-2 right-4 bg-primary">
                      Popular
                    </Badge>
                  )}
                  <div className="mb-4">
                    <div className="flex items-center gap-2 mb-2">
                      <plan.icon className="h-5 w-5 text-primary" />
                      <h3 className="font-semibold">{plan.name}</h3>
                    </div>
                    <p className="text-xs text-muted-foreground">
                      {plan.description}
                    </p>
                  </div>
                  <div className="mb-4">
                    <span className="text-2xl font-bold">{plan.price}</span>
                    <span className="text-sm text-muted-foreground">
                      {" "}
                      / {plan.period}
                    </span>
                  </div>
                  <ul className="mb-4 space-y-2 flex-1">
                    {plan.features.map((feature, index) => (
                      <li
                        key={index}
                        className="flex items-start gap-2 text-xs"
                      >
                        <Check className="h-3 w-3 text-primary mt-0.5 shrink-0" />
                        <span>{feature}</span>
                      </li>
                    ))}
                  </ul>
                  <Button
                    variant={isCurrentPlan ? "outline" : plan.popular ? "default" : "outline"}
                    size="sm"
                    className="w-full"
                    disabled={isCurrentPlan}
                  >
                    {isCurrentPlan ? (
                      "Current Plan"
                    ) : plan.id === "enterprise" ? (
                      "Contact Sales"
                    ) : (
                      <>
                        Upgrade
                        <ArrowRight className="ml-1 h-3 w-3" />
                      </>
                    )}
                  </Button>
                </div>
              );
            })}
          </div>
        </CardContent>
      </Card>

      {/* Payment Methods - Card Visual */}
      <Card>
        <CardHeader>
          <CardTitle>Saved Cards</CardTitle>
          <CardDescription>
            Select the card you want to use for payments. You can save up to 3 cards.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {paymentMethods.map((card) => (
              <CreditCardVisual
                key={card.id}
                card={card}
                onSetDefault={() => handleSetDefault(card.id)}
                onRemove={() => handleRemoveCard(card.id)}
              />
            ))}
            {paymentMethods.length < 3 && (
              <AddCardPlaceholder onClick={handleAddCard} />
            )}
          </div>

          {defaultCard && (
            <div className="flex items-center gap-2 mt-4 text-sm text-muted-foreground">
              <Info className="h-4 w-4" />
              <span>
                Card ending in {defaultCard.last4} is used as default
              </span>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Billing History */}
      <Card>
        <CardHeader>
          <CardTitle>Billing History</CardTitle>
          <CardDescription>
            View your past invoices and payment history.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex flex-col items-center justify-center py-8 text-center">
            <p className="text-sm text-muted-foreground">
              No billing history yet
            </p>
            <p className="text-xs text-muted-foreground mt-1">
              Your invoices will appear here after your first payment
            </p>
          </div>
        </CardContent>
      </Card>

      {/* Usage */}
      <Card>
        <CardHeader>
          <CardTitle>Usage This Month</CardTitle>
          <CardDescription>Track your resource consumption.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div>
            <div className="flex items-center justify-between text-sm mb-2">
              <span>Lab Environments</span>
              <span className="font-medium">1 / 3</span>
            </div>
            <div className="h-2 rounded-full bg-secondary">
              <div
                className="h-2 rounded-full bg-primary"
                style={{ width: "33%" }}
              />
            </div>
          </div>
          <Separator />
          <div>
            <div className="flex items-center justify-between text-sm mb-2">
              <span>Lab Hours</span>
              <span className="font-medium">2h / 10h</span>
            </div>
            <div className="h-2 rounded-full bg-secondary">
              <div
                className="h-2 rounded-full bg-primary"
                style={{ width: "20%" }}
              />
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
